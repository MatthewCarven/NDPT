"""Pinging several hosts side by side."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Iterable

from ndpt.core.backends.base import Prober
from ndpt.core.models import PingTarget, ProbeResult, ProbeStatus
from ndpt.core.resolve import Resolver, ResolveError
from ndpt.core.session import Session, notify
from ndpt.core.snapshot import PingSnapshot, StatsSnapshot, TargetSnapshot
from ndpt.core.stats import RollingStats


class PingSession(Session):
    """Pings each host every `interval` seconds, whether or not the last answer is back.

    A steady beat keeps the charts evenly spaced; with a timeout longer than the
    interval, probes overlap. `count` stops each host after that many probes.

    Hosts can come and go while it runs (`add`, `remove`). `run()` ends once
    every host has finished, or with `until_stopped` only at `stop()`, which
    lets a front end start with no hosts at all and add them as it goes.
    """

    def __init__(self, hosts: Iterable[str], prober: Prober, *, resolver: Resolver | None = None,
                 family: int = socket.AF_UNSPEC, interval: float = 1.0, timeout: float = 1.0,
                 size: int = 32, count: int | None = None, ttl: int = 64,
                 window: int = 300, until_stopped: bool = False) -> None:
        super().__init__(prober, resolver=resolver, family=family, interval=interval,
                         timeout=timeout, size=size, window=window)
        if count is not None and count < 1:
            raise ValueError("count must be at least 1")
        self.targets = [PingTarget(host, stats=RollingStats(window)) for host in hosts]
        if not self.targets and not until_stopped:
            raise ValueError("nothing to ping")
        self.count = count
        self.ttl = ttl
        self.until_stopped = until_stopped
        self.listeners: list[Callable[[PingTarget, ProbeResult], None]] = []
        self._group: asyncio.TaskGroup | None = None   # set while run() takes new hosts
        self._drives: dict[int, asyncio.Task] = {}     # id(target) -> its task

    def add(self, host: str) -> PingTarget:
        """Start pinging another host: at once if the session is running, else when it runs."""
        target = PingTarget(host, stats=RollingStats(self.window))
        self.targets.append(target)
        if self._group is not None:
            self._start(target)
        return target

    def remove(self, target: PingTarget) -> None:
        """Stop pinging a host and forget it. Its answers still on their way are dropped."""
        self.targets.remove(target)
        task = self._drives.pop(id(target), None)
        if task is not None:
            task.cancel()

    def snapshot(self) -> PingSnapshot:
        """A frozen copy of every host's state, for another thread. Call it on the session's loop."""
        targets = tuple(TargetSnapshot(id(t), t.name, t.address, t.error, t.last_status,
                                       StatsSnapshot.of(t.stats)) for t in self.targets)
        return PingSnapshot(self.prober.name, self.interval, self.base_interval, self.paused, targets)

    async def run(self) -> None:
        async with asyncio.TaskGroup() as group:
            self._group = group
            try:
                for target in self.targets:
                    self._start(target)
                await self._until_done()
            finally:
                self._group = None  # from here on, add() only lists a host

    def _start(self, target: PingTarget) -> None:
        key = id(target)

        def forget(task: asyncio.Task) -> None:
            if self._drives.get(key) is task:
                del self._drives[key]

        task = self._group.create_task(self._host(target))
        self._drives[key] = task
        task.add_done_callback(forget)

    async def _until_done(self) -> None:
        """Wait for stop(), or (unless `until_stopped`) for every host to finish."""
        stopped = asyncio.ensure_future(self._stop.wait())
        try:
            while not self.stopping:
                live = [task for task in self._drives.values() if not task.done()]
                if not live and not self.until_stopped:
                    return
                await asyncio.wait([stopped, *live], return_when=asyncio.FIRST_COMPLETED)
        finally:
            stopped.cancel()

    async def _host(self, target: PingTarget) -> None:
        try:
            target.address = await self.resolver.resolve(target.name, self.family)
        except ResolveError as e:
            target.error = str(e)
            return
        await self._drive(target)

    async def _drive(self, target: PingTarget) -> None:
        loop = asyncio.get_running_loop()
        inflight: set[asyncio.Task] = set()
        sent = 0
        next_at = loop.time()
        try:
            while not self.stopping:
                if self.paused:
                    if await self._hold():
                        break
                    next_at = loop.time()
                task = asyncio.create_task(self._ping(target))
                inflight.add(task)
                task.add_done_callback(inflight.discard)
                sent += 1
                if self.count is not None and sent >= self.count:
                    break
                next_at = await self._next_beat(next_at)
                if next_at is None:
                    break
            await self._finish(inflight)
        except asyncio.CancelledError:
            for task in inflight:  # removed, or run() itself was cancelled
                task.cancel()
            raise

    async def _ping(self, target: PingTarget) -> None:
        result = await self._probe(target.address, self.ttl)
        replied = result.status is ProbeStatus.REPLY
        target.stats.add(result.rtt_ms if replied else None, result.sent_at)
        target.last_status = result.status
        notify(self.listeners, target, result)
