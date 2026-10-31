"""What ping and trace sessions have in common: settings, stopping, safe probing."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from collections.abc import Callable, Iterable

from ndpt.core.backends.base import Prober
from ndpt.core.models import ProbeResult, ProbeStatus
from ndpt.core.resolve import Resolver

log = logging.getLogger(__name__)

MAX_PAYLOAD = 65500  # the most the Windows ICMP API accepts
INTERVAL_STEPS = (1.0, 2.0, 5.0, 10.0, 15.0, 30.0, 60.0)  # what slower() and faster() step through


class Session:
    """A run of probes on a steady beat. Front ends watch it two ways:

    - read its state (targets / hops and their stats) on their own refresh timer;
    - add a listener to hear each result as it lands (called on the session's loop).

    `stop()`, `pause()`, `resume()`, `slower()`, `faster()` and `set_interval()`
    must be called on the session's own loop; from another thread use
    `loop.call_soon_threadsafe(session.stop)`.
    """

    def __init__(self, prober: Prober, *, resolver: Resolver | None, family: int,
                 interval: float, timeout: float, size: int, window: int) -> None:
        if interval <= 0:
            raise ValueError("interval must be positive")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        if not 0 <= size <= MAX_PAYLOAD:
            raise ValueError(f"size must be between 0 and {MAX_PAYLOAD}")
        self.prober = prober
        self.resolver = resolver or Resolver()
        self.family = family if family is not None else socket.AF_UNSPEC
        self.interval = interval
        self.base_interval = interval  # faster() goes no lower than this
        self.timeout = timeout
        self.size = size
        self.window = window
        self._stop = asyncio.Event()
        self._wake = asyncio.Event()   # set by stop(); pulsed by set_interval()
        self._retimes = 0              # how many times the interval has changed
        self._resumed = asyncio.Event()
        self._resumed.set()

    @property
    def stopping(self) -> bool:
        return self._stop.is_set()

    @property
    def paused(self) -> bool:
        return not self._resumed.is_set()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()     # end any sleep
        self._resumed.set()  # wake anything held by pause()

    def pause(self) -> None:
        """Send nothing more until resume(). Answers already on their way still land."""
        if not self._stop.is_set():
            self._resumed.clear()

    def resume(self) -> None:
        self._resumed.set()

    def set_interval(self, seconds: float) -> None:
        """Change the time between beats, from the beat already sent: a session
        waiting out a long interval doesn't finish that wait before speeding up."""
        if seconds <= 0:
            raise ValueError("interval must be positive")
        self.interval = seconds
        self._retimes += 1
        self._wake.set()  # a pulse: whoever is sleeping now wakes and looks again
        if not self._stop.is_set():
            self._wake.clear()

    def slower(self) -> float:
        """A step longer between beats (see INTERVAL_STEPS), up to a minute. Returns the new interval."""
        longer = [s for s in self._steps() if s > self.interval]
        if longer:
            self.set_interval(longer[0])
        return self.interval

    def faster(self) -> float:
        """A step shorter between beats, but never below the interval the session started with."""
        shorter = [s for s in self._steps() if s < self.interval]
        if shorter:
            self.set_interval(shorter[-1])
        return self.interval

    def _steps(self) -> list[float]:
        return sorted({self.base_interval, *(s for s in INTERVAL_STEPS if s > self.base_interval)})

    async def _hold(self) -> bool:
        """Wait while paused. True if a stop was asked for meanwhile.

        Callers take their beat up again from the moment they resume, so a
        long pause isn't followed by a burst of catching up.
        """
        await self._resumed.wait()
        return self._stop.is_set()

    async def _sleep(self, delay: float) -> bool:
        """Wait up to `delay` seconds. True if a stop was asked for meanwhile.

        Always yields to the loop, even when behind schedule (delay <= 0, easy
        with Windows' ~15 ms timer), so probes already in flight get to land
        before the next beat sends more. A change of interval ends it early.
        """
        if self._stop.is_set():
            return True
        if delay <= 0:
            await asyncio.sleep(0)
        else:
            try:
                async with asyncio.timeout(delay):
                    await self._wake.wait()
            except TimeoutError:
                pass
        return self._stop.is_set()

    async def _next_beat(self, due: float) -> float | None:
        """Wait for the beat after the one due at `due` (loop time) and return when that is,
        or None if a stop was asked for meanwhile.

        A late beat goes at once, with no burst of catching up. An interval
        changed during the wait counts from `due` straight away.
        """
        loop = asyncio.get_running_loop()
        while True:
            retimes = self._retimes
            next_due = max(due + self.interval, loop.time())  # fell behind: carry on, don't burst
            if await self._sleep(next_due - loop.time()):
                return None
            if self._retimes == retimes:
                return next_due

    async def _probe(self, dest: str, ttl: int) -> ProbeResult:
        """One probe that always returns a result: a prober bug becomes an ERROR, not a lost task."""
        try:
            return await self.prober.probe(dest, ttl=ttl, timeout=self.timeout, size=self.size)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.exception("prober %s failed probing %s", self.prober.name, dest)
            return ProbeResult(dest, ttl, ProbeStatus.ERROR, None, None, time.time(), repr(e))

    async def _finish(self, inflight: set[asyncio.Task]) -> None:
        """Let probes still in flight land, unless we're stopping, in which case drop them."""
        if self._stop.is_set():
            for task in inflight:
                task.cancel()
        await asyncio.gather(*inflight, return_exceptions=True)


def notify(listeners: Iterable[Callable[..., None]], *args: object) -> None:
    for listener in list(listeners):
        try:
            listener(*args)
        except Exception:
            log.exception("listener %r failed", listener)
