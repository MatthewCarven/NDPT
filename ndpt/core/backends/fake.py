"""A prober that answers from scripted routes instead of the network.

Used by the tests (deterministic, instant) and by `--demo` (a plausible
made-up internet, answering in real time, no packets sent).
"""

from __future__ import annotations

import asyncio
import ipaddress
import random
import socket
import time
import zlib
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ndpt.core.backends.base import Prober
from ndpt.core.models import ProbeResult, ProbeStatus
from ndpt.core.resolve import Resolver


@dataclass
class FakeHop:
    """One router on a fake route, or the destination itself if it's the last entry."""

    address: str | tuple[str, ...] | None  # None never answers; a tuple answers in turn (load balancing)
    latency_ms: float = 1.0
    jitter_ms: float = 0.0
    loss: float = 0.0                       # chance that a probe gets no answer
    rtts: Sequence[float | None] | None = None  # if set, cycled through instead of random samples
    status: ProbeStatus | None = None       # force the answer, e.g. UNREACHABLE to end a route in a dead end


class FakeProber(Prober):
    """Answers probes from `routes`: {destination address: [FakeHop for TTL 1, 2, ...]}.

    `route_factory(dest)` invents a route for any destination not listed.
    `time_scale` turns simulated latency into real waiting; 0 answers at once,
    without even yielding, so tests see each result as soon as its task runs.
    """

    name = "fake"
    supports_ttl = True

    def __init__(self, routes: dict[str, list[FakeHop]] | None = None, *,
                 route_factory: Callable[[str], list[FakeHop]] | None = None,
                 seed: int = 0, time_scale: float = 0.0) -> None:
        self.routes = dict(routes or {})
        self.route_factory = route_factory
        self.time_scale = time_scale
        self.probes: list[tuple[str, int]] = []  # (dest, ttl) of every probe sent, for tests
        self._rng = random.Random(seed)
        self._turns: Counter[tuple[str, int]] = Counter()

    async def probe(self, dest: str, *, ttl: int = 64, timeout: float = 1.0,
                    size: int = 32) -> ProbeResult:
        sent_at = time.time()
        self.probes.append((dest, ttl))
        route = self.routes.get(dest)
        if route is None and self.route_factory is not None:
            route = self.routes[dest] = self.route_factory(dest)
        if not route:
            return await self._timeout(dest, ttl, timeout, sent_at)

        index = min(ttl, len(route)) - 1
        hop = route[index]
        turn = self._turns[(dest, index)]
        self._turns[(dest, index)] += 1
        responder = hop.address[turn % len(hop.address)] if isinstance(hop.address, tuple) else hop.address
        rtt = self._sample(hop, turn)
        if responder is None or rtt is None or rtt > timeout * 1000:
            return await self._timeout(dest, ttl, timeout, sent_at)

        if self.time_scale:
            await asyncio.sleep(rtt / 1000 * self.time_scale)
        reached = index == len(route) - 1
        status = hop.status or (ProbeStatus.REPLY if reached else ProbeStatus.TTL_EXPIRED)
        return ProbeResult(dest, ttl, status, responder, rtt, sent_at)

    def _sample(self, hop: FakeHop, turn: int) -> float | None:
        if hop.rtts is not None:
            return hop.rtts[turn % len(hop.rtts)]
        if self._rng.random() < hop.loss:
            return None
        return max(0.05, self._rng.gauss(hop.latency_ms, hop.jitter_ms))

    async def _timeout(self, dest: str, ttl: int, timeout: float, sent_at: float) -> ProbeResult:
        if self.time_scale:
            await asyncio.sleep(timeout * self.time_scale)
        return ProbeResult(dest, ttl, ProbeStatus.TIMEOUT, None, None, sent_at)


def demo_route(dest: str) -> list[FakeHop]:
    """A plausible made-up route to `dest`; the same route every time for the same address.

    Router addresses come from the documentation ranges, so nothing real is named.
    """
    rng = random.Random(dest)
    length = rng.randint(8, 14)
    hops = [FakeHop("192.168.1.1", 0.8, 0.3)]
    latency = 0.8
    for _ in range(2, length):
        latency += rng.uniform(0.5, 6.0)
        roll = rng.random()
        if roll < 0.08:
            hops.append(FakeHop(None))  # a router that never sends "time exceeded"
        elif roll < 0.2:
            # Replies slowly and drops some: it de-prioritises ICMP, the traffic itself is fine.
            hops.append(FakeHop(_demo_router(rng), latency + rng.uniform(15, 40), 8.0, loss=0.25))
        else:
            hops.append(FakeHop(_demo_router(rng), latency, 0.4 + latency * 0.03, loss=0.003))
    hops.append(FakeHop(dest, latency + rng.uniform(0.5, 3.0), 0.5 + latency * 0.03, loss=0.01))
    return hops


def _demo_router(rng: random.Random) -> str:
    return f"{rng.choice(('192.0.2', '198.51.100'))}.{rng.randint(1, 254)}"


def demo_address(host: str) -> str:
    """A stable made-up address for a host name (203.0.113.0/24, the documentation range)."""
    return f"203.0.113.{1 + zlib.crc32(host.encode()) % 254}"


class DemoResolver(Resolver):
    """Resolves every name to a made-up address and names every router, with no DNS traffic."""

    async def resolve(self, host: str, family: int = socket.AF_UNSPEC) -> str:
        try:
            return str(ipaddress.ip_address(host))
        except ValueError:
            pass
        address = demo_address(host)
        self._names[address] = host
        return address

    async def reverse(self, address: str) -> str | None:
        if address not in self._names:
            self._names[address] = f"r{address.replace('.', '-')}.demo.invalid"
        return self._names[address]
