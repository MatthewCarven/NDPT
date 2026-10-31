"""The bridge between the Qt thread and the engine's loop thread.

Sessions run on a `core.runner.LoopThread`, never on the Qt thread, so a slow
probe or a DNS lookup can't freeze the window. The Qt thread doesn't touch a
running session at all: it asks for things to be done on the loop (add a host,
pause, stop), and hears back through Qt signals carrying snapshots (frozen
copies) and path events. A signal emitted on the loop thread is queued, and
its slots run on the Qt thread.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import QObject, Signal

from ndpt.core.backends import Prober
from ndpt.core.ping import PingSession
from ndpt.core.resolve import Resolver
from ndpt.core.runner import LoopThread
from ndpt.core.session import Session
from ndpt.core.trace import TraceSession

log = logging.getLogger(__name__)

REFRESH = 0.25  # seconds between snapshots of a session that has news


@dataclass(frozen=True)
class Settings:
    """How the GUI probes. Changing them restarts the sessions (see MainWindow)."""

    interval: float = 1.0
    timeout: float = 1.0
    size: int = 32
    family: int = socket.AF_UNSPEC
    max_hops: int = 30
    lookup_names: bool = True
    protocol: str = "icmp"   # or "tcp", which can't trace
    port: int = 443          # for tcp


class Runner(QObject):
    """One session on the loop thread, reporting to the Qt thread.

    `updated` carries a snapshot whenever the session has news (at most every
    `refresh` seconds); `finished` comes once, after the last snapshot. Every
    signal carries the runner first, so a view can tell its current runner's
    news from a stopped one's last words (a queued signal still arrives after
    `disconnect`, and `QObject.sender()` is None in a wrapped slot).
    """

    updated = Signal(object, object)  # (runner, snapshot)
    finished = Signal(object)         # (runner)

    def __init__(self, engine: Engine, session: Session) -> None:
        super().__init__()
        self.engine = engine
        self._session = session          # from here on, touched only on the loop thread
        self._task: asyncio.Task | None = None
        self._news = True
        self.finished.connect(self._forget)  # a slot of this QObject, so it runs on the Qt thread

    def start(self) -> None:
        self.engine.runners.add(self)
        self.engine.loop.submit(self._run())

    def _forget(self, _: Runner) -> None:
        self.engine.runners.discard(self)

    def stop(self) -> None:
        self._on_loop(Session.stop)

    def pause(self) -> None:
        self._on_loop(Session.pause)

    def resume(self) -> None:
        self._on_loop(Session.resume)

    def slower(self) -> None:
        self._on_loop(Session.slower)

    def faster(self) -> None:
        self._on_loop(Session.faster)

    def _on_loop(self, fn: Callable[..., Any], *args: Any) -> None:
        """Call `fn(session, *args)` on the loop thread, then send a fresh snapshot."""
        def run() -> None:
            fn(self._session, *args)
            self._news = True
        self.engine.loop.call(run)

    def _heard(self, *_: object) -> None:  # a session listener, so on the loop thread
        self._news = True

    async def _run(self) -> None:
        self._task = asyncio.current_task()
        session = self._session
        work = asyncio.create_task(session.run())
        try:
            while not work.done():
                await asyncio.wait({work}, timeout=self.engine.refresh)
                if self._news:
                    self._news = False
                    self.updated.emit(self, session.snapshot())
            work.result()
        except Exception:
            log.exception("%s failed", type(session).__name__)
        finally:
            if not work.done():  # cancelled by the loop shutting down
                session.stop()
                work.cancel()
                await asyncio.gather(work, return_exceptions=True)
            self.updated.emit(self, session.snapshot())
            self.finished.emit(self)


class PingRunner(Runner):
    def __init__(self, engine: Engine, session: PingSession) -> None:
        super().__init__(engine, session)
        session.listeners.append(self._heard)

    def add(self, host: str) -> None:
        self._on_loop(PingSession.add, host)

    def remove(self, key: int) -> None:
        """Stop pinging the host whose snapshot has this key."""
        def remove(session: PingSession) -> None:
            for target in session.targets:
                if id(target) == key:
                    session.remove(target)
                    return
        self._on_loop(remove)


class TraceRunner(Runner):
    event = Signal(object, str, int)  # (runner, a path event, the round it came in)

    def __init__(self, engine: Engine, session: TraceSession) -> None:
        super().__init__(engine, session)
        session.listeners.append(self._heard)
        session.event_listeners.append(lambda text: self.event.emit(self, text, session.round))


class Engine:
    """The loop thread, the prober and the name cache, shared by every session the GUI runs.

    Everything here is called from the Qt thread. `prober` is the one new
    sessions get; swapping it closes the old one on the loop once the sessions
    using it have stopped.
    """

    def __init__(self, prober: Prober, resolver: Resolver, *, refresh: float = REFRESH) -> None:
        self.prober = prober
        self.resolver = resolver
        self.refresh = refresh
        self.loop = LoopThread().start()
        self.runners: set[Runner] = set()  # started and not yet finished
        self.closed = False

    # ping() and trace() hand back a runner that hasn't started: connect its signals, then
    # start() it. A session can finish at once (a name that won't resolve), and a signal
    # emitted before anyone is connected is lost.

    def ping(self, hosts: list[str], settings: Settings) -> PingRunner:
        session = PingSession(hosts, self.prober, resolver=self.resolver, family=settings.family,
                              interval=settings.interval, timeout=settings.timeout,
                              size=settings.size, until_stopped=True)
        return PingRunner(self, session)

    def trace(self, host: str, settings: Settings) -> TraceRunner:
        """Raises ValueError if the prober can't trace (TCP)."""
        session = TraceSession(host, self.prober, resolver=self.resolver, family=settings.family,
                               max_hops=settings.max_hops, interval=settings.interval,
                               timeout=settings.timeout, size=settings.size,
                               lookup_names=settings.lookup_names)
        return TraceRunner(self, session)

    def swap_prober(self, prober: Prober) -> None:
        """New sessions use `prober`. Stop the old sessions first: the old prober closes after them."""
        old, self.prober = self.prober, prober
        self.loop.submit(self._close(old, list(self.runners)))

    def shutdown(self, timeout: float = 3.0) -> None:
        """Stop every session, close the prober, and stop the loop thread. Blocks until done."""
        if self.closed:
            return
        self.closed = True
        runners = list(self.runners)
        for runner in runners:
            runner.stop()
        try:
            self.loop.submit(self._close(self.prober, runners)).result(timeout)
        except Exception:
            log.exception("closing the engine took too long")
        self.loop.stop(timeout)

    @staticmethod
    async def _close(prober: Prober, runners: list[Runner]) -> None:
        """Let `runners` (already told to stop) wind up, then close `prober`. On the loop thread."""
        tasks = [r._task for r in runners if r._task is not None and not r._task.done()]
        if tasks:
            await asyncio.wait(tasks, timeout=2.0)
        await prober.aclose()
