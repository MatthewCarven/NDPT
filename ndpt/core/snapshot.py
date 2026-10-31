"""Frozen copies of a session's state, for front ends that read it from another thread.

The GUI runs its sessions on a loop thread (`core.runner.LoopThread`) and never
touches a live session from the Qt thread: each session builds a snapshot on
its own loop, and the copy is what crosses over.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ndpt.core.models import ProbeStatus
from ndpt.core.stats import RollingStats


@dataclass(frozen=True, slots=True)
class StatsSnapshot:
    sent: int
    received: int
    last: float | None
    best: float | None
    worst: float | None
    avg: float | None
    stdev: float | None
    jitter: float | None   # None until there are two answers to compare
    p95: float | None
    history: tuple[tuple[float, float | None], ...]  # (time.time() sent, rtt or None), oldest first

    @property
    def lost(self) -> int:
        return self.sent - self.received

    @property
    def loss_pct(self) -> float:
        return 100.0 * self.lost / self.sent if self.sent else 0.0

    @classmethod
    def of(cls, stats: RollingStats) -> StatsSnapshot:
        return cls(stats.sent, stats.received, stats.last, stats.best, stats.worst, stats.avg,
                   stats.stdev, stats.jitter if stats.received > 1 else None,
                   stats.percentile(95), tuple(stats.history))


@dataclass(frozen=True, slots=True)
class TargetSnapshot:
    key: int                  # the same for one host for as long as it's in the session
    name: str
    address: str | None
    error: str | None
    last_status: ProbeStatus | None
    stats: StatsSnapshot


@dataclass(frozen=True, slots=True)
class PingSnapshot:
    prober: str
    interval: float
    base_interval: float      # what it started with: faster() goes no lower
    paused: bool
    targets: tuple[TargetSnapshot, ...]


@dataclass(frozen=True, slots=True)
class Responder:
    address: str
    count: int                # answers from it at this hop
    name: str | None          # once its reverse lookup has landed


@dataclass(frozen=True, slots=True)
class HopSnapshot:
    ttl: int
    responders: tuple[Responder, ...]  # most answers first
    last_status: ProbeStatus | None
    stats: StatsSnapshot

    @property
    def address(self) -> str | None:
        return self.responders[0].address if self.responders else None

    @property
    def name(self) -> str | None:
        return self.responders[0].name if self.responders else None


@dataclass(frozen=True, slots=True)
class TraceSnapshot:
    prober: str
    host: str
    address: str | None
    error: str | None
    round: int
    interval: float
    base_interval: float
    paused: bool
    dest_ttl: int | None
    hops: tuple[HopSnapshot, ...]  # the visible ones
    notes: tuple[str, ...]
    events: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Carried:
    """How much of one hop's loss and latency carries on to the hops after it."""

    loss_pct: float | None
    avg: float | None
    loss_stops_here: bool = False  # the hop shows more loss than carries on
    slow_to_reply: bool = False    # its average is well over what carries on (as TraceSession.notes)


def carried_on(hops: Sequence[HopSnapshot]) -> list[Carried]:
    """For each hop, the least loss and the lowest average of it and of every later hop that answers.

    A probe to a later hop passes through this one, so loss or delay that really
    happens here shows at every hop after it too. Whatever a hop shows beyond
    that is how the router answers traceroute (slowly, rate-limited), not what
    it does to traffic. A hop that never answers gets None for both.
    """
    carried = []
    loss: float | None = None
    avg: float | None = None
    for hop in reversed(hops):
        s = hop.stats
        if not s.received:
            carried.append(Carried(None, None))
            continue
        loss = s.loss_pct if loss is None else min(loss, s.loss_pct)
        avg = s.avg if avg is None else min(avg, s.avg)
        carried.append(Carried(loss, avg, s.loss_pct > loss,
                               s.avg >= avg + 10 and s.avg >= avg * 1.5))
    return carried[::-1]
