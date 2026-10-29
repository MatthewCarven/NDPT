"""Tracing a route, mtr-style."""

from __future__ import annotations

import asyncio
import socket
from collections.abc import Callable

from ndpt.core.backends.base import Prober
from ndpt.core.models import Hop, ProbeResult, ProbeStatus
from ndpt.core.resolve import Resolver, ResolveError
from ndpt.core.session import Session, notify
from ndpt.core.stats import RollingStats


class TraceSession(Session):
    """Finds the hops to a host, then keeps probing every one of them, round after round.

    Round 1 sends TTL 1, 2, 3, ... a few milliseconds apart and stops sending
    once the destination itself answers; later rounds probe exactly that many
    hops. `rounds` stops after that many rounds.
    """

    def __init__(self, host: str, prober: Prober, *, resolver: Resolver | None = None,
                 family: int = socket.AF_UNSPEC, max_hops: int = 30, interval: float = 1.0,
                 timeout: float = 1.0, size: int = 32, rounds: int | None = None,
                 window: int = 300, stagger: float | None = None,
                 lookup_names: bool = True) -> None:
        super().__init__(prober, resolver=resolver, family=family, interval=interval,
                         timeout=timeout, size=size, window=window)
        if not prober.supports_ttl:
            raise ValueError(f"the {prober.name} prober can't set TTLs, so it can't trace")
        if not 1 <= max_hops <= 255:
            raise ValueError("max_hops must be between 1 and 255")
        if rounds is not None and rounds < 1:
            raise ValueError("rounds must be at least 1")
        self.host = host
        self.address: str | None = None
        self.error: str | None = None
        self.max_hops = max_hops
        self.rounds = rounds
        self.round = 0
        self.lookup_names = lookup_names
        self.stagger = min(0.025, interval / (2 * max_hops)) if stagger is None else stagger
        self.hops: list[Hop] = []
        self.dest_ttl: int | None = None  # the hop at which the destination answers
        self.events: list[str] = []       # path changes, oldest first
        self.listeners: list[Callable[[Hop, ProbeResult], None]] = []
        self.event_listeners: list[Callable[[str], None]] = []
        self._reached_before = False
        self._lookups: set[asyncio.Task] = set()

    @property
    def visible_hops(self) -> list[Hop]:
        """Hops worth showing: up to the destination, or one past the last hop that answered."""
        if self.dest_ttl is not None:
            return self.hops[:self.dest_ttl]
        answered = [hop.ttl for hop in self.hops if hop.stats.received]
        return self.hops[:min(len(self.hops), (max(answered) if answered else 0) + 1)]

    async def run(self) -> None:
        try:
            self.address = await self.resolver.resolve(self.host, self.family)
        except ResolveError as e:
            self.error = str(e)
            return
        self.hops = [self._new_hop(ttl) for ttl in range(1, self.max_hops + 1)]
        loop = asyncio.get_running_loop()
        inflight: set[asyncio.Task] = set()
        next_at = loop.time()
        try:
            while not self.stopping:
                self.round += 1
                round_no = self.round
                ttl = 1
                while ttl <= len(self.hops):  # shrinks as soon as the destination answers
                    task = asyncio.create_task(self._trace(ttl, round_no))
                    inflight.add(task)
                    task.add_done_callback(inflight.discard)
                    ttl += 1
                    if self.stagger and ttl <= len(self.hops) and await self._sleep(self.stagger):
                        break
                if self.stopping or (self.rounds is not None and self.round >= self.rounds):
                    break
                next_at = max(next_at + self.interval, loop.time())
                if await self._sleep(next_at - loop.time()):
                    break
            await self._finish(inflight)
            if self._lookups and not self.stopping:
                await asyncio.wait(self._lookups, timeout=self.timeout)  # let hop names land
        finally:
            for task in self._lookups:
                task.cancel()

    def notes(self, min_samples: int = 10) -> list[str]:
        """Plain-language warnings about intermediate hops that look worse than they are.

        Routers answer traceroute probes as a low-priority chore, and rate-limit
        those answers. Loss or delay at one hop that the hops after it don't
        share is how that router answers, not what happens to your traffic.
        """
        hops = [hop for hop in self.visible_hops if hop.stats.sent >= min_samples]
        notes = []
        for i, hop in enumerate(hops):
            later = [h for h in hops[i + 1:] if h.stats.received]
            if not hop.stats.received or not later:
                continue
            loss = hop.stats.loss_pct
            if loss >= 10 and min(h.stats.loss_pct for h in later) <= loss / 2:
                notes.append(f"hop {hop.ttl}: its {loss:.0f}% loss stops there, so that router is "
                             "rate-limiting its replies, not dropping your traffic")
            later_avg = min(h.stats.avg for h in later)
            if hop.stats.avg >= later_avg + 10 and hop.stats.avg >= later_avg * 1.5:
                notes.append(f"hop {hop.ttl}: slower than the hops after it, so that router is "
                             "slow to reply, not slow to forward")
        return notes

    def _new_hop(self, ttl: int) -> Hop:
        return Hop(ttl, RollingStats(self.window))

    async def _trace(self, ttl: int, round_no: int) -> None:
        result = await self._probe(self.address, ttl)
        self._record(ttl, result, round_no)

    def _record(self, ttl: int, result: ProbeResult, round_no: int) -> None:
        if ttl > len(self.hops):
            return  # past the destination: the same reply again, already counted at its hop
        status = result.status
        if status in (ProbeStatus.REPLY, ProbeStatus.UNREACHABLE) and (
                self.dest_ttl is None or ttl < self.dest_ttl):
            self._set_destination(ttl, result, round_no)
        elif status is ProbeStatus.TTL_EXPIRED and ttl == self.dest_ttl:
            self._path_grew(ttl)
        hop = self.hops[ttl - 1]
        hop.stats.add(result.rtt_ms if status.answered else None, result.sent_at)
        hop.last_status = status
        if status.answered and result.responder:
            self._saw(hop, result.responder)
        notify(self.listeners, hop, result)

    def _set_destination(self, ttl: int, result: ProbeResult, round_no: int) -> None:
        first = not self._reached_before
        self.dest_ttl = ttl
        self._reached_before = True
        del self.hops[ttl:]
        if result.status is ProbeStatus.UNREACHABLE:
            self._event(f"hop {ttl} ({result.responder}) says {result.detail or 'unreachable'}")
        elif first:
            self._event(f"reached {self.address} at hop {ttl}")
        elif round_no > 1:
            self._event(f"destination now at hop {ttl}")

    def _path_grew(self, ttl: int) -> None:
        self.dest_ttl = None
        self.hops.extend(self._new_hop(t) for t in range(len(self.hops) + 1, self.max_hops + 1))
        self._event(f"hop {ttl} is a router now, not the destination: the path got longer")

    def _saw(self, hop: Hop, responder: str) -> None:
        is_new = responder not in hop.responders
        had_others = bool(hop.responders)
        hop.responders[responder] += 1
        hop.last_responder = responder
        if not is_new:
            return
        if had_others:
            self._event(f"hop {hop.ttl}: also answered by {responder}")
        if self.lookup_names:
            task = asyncio.ensure_future(self.resolver.reverse(responder))
            self._lookups.add(task)
            task.add_done_callback(self._lookups.discard)

    def _event(self, text: str) -> None:
        self.events.append(text)
        notify(self.event_listeners, text)
