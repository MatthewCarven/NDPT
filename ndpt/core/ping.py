"""Pinging several hosts side by side."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable, Iterable

from ndpt.core.backends.base import Prober
from ndpt.core.models import PingTarget, ProbeResult, ProbeStatus
from ndpt.core.resolve import Resolver, ResolveError
from ndpt.core.session import Session, notify
from ndpt.core.stats import RollingStats


class PingSession(Session):
    """Pings each host every `interval` seconds, whether or not the last answer is back.

    A steady beat keeps the charts evenly spaced; with a timeout longer than the
    interval, probes overlap. `count` stops each host after that many probes.
    """

    def __init__(self, hosts: Iterable[str], prober: Prober, *, resolver: Resolver | None = None,
                 family: int = socket.AF_UNSPEC, interval: float = 1.0, timeout: float = 1.0,
                 size: int = 32, count: int | None = None, ttl: int = 64,
                 window: int = 300) -> None:
        super().__init__(prober, resolver=resolver, family=family, interval=interval,
                         timeout=timeout, size=size, window=window)
        if count is not None and count < 1:
            raise ValueError("count must be at least 1")
        self.targets = [PingTarget(host, stats=RollingStats(window)) for host in hosts]
        if not self.targets:
            raise ValueError("nothing to ping")
        self.count = count
        self.ttl = ttl
        self.listeners: list[Callable[[PingTarget, ProbeResult], None]] = []

    async def run(self) -> None:
        await asyncio.gather(*(self._resolve(t) for t in self.targets))
        async with asyncio.TaskGroup() as group:
            for target in self.targets:
                if target.address is not None:
                    group.create_task(self._drive(target))

    async def _resolve(self, target: PingTarget) -> None:
        try:
            target.address = await self.resolver.resolve(target.name, self.family)
        except ResolveError as e:
            target.error = str(e)

    async def _drive(self, target: PingTarget) -> None:
        loop = asyncio.get_running_loop()
        inflight: set[asyncio.Task] = set()
        sent = 0
        next_at = loop.time()
        while not self.stopping:
            task = asyncio.create_task(self._ping(target))
            inflight.add(task)
            task.add_done_callback(inflight.discard)
            sent += 1
            if self.count is not None and sent >= self.count:
                break
            next_at = max(next_at + self.interval, loop.time())  # fell behind: carry on, don't burst
            if await self._sleep(next_at - loop.time()):
                break
        await self._finish(inflight)

    async def _ping(self, target: PingTarget) -> None:
        result = await self._probe(target.address, self.ttl)
        replied = result.status is ProbeStatus.REPLY
        target.stats.add(result.rtt_ms if replied else None, result.sent_at)
        target.last_status = result.status
        notify(self.listeners, target, result)
