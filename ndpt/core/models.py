"""Plain data passed between probers, sessions and front ends."""

from __future__ import annotations

import enum
from collections import Counter
from dataclasses import dataclass, field

from ndpt.core.stats import RollingStats


class ProbeStatus(enum.Enum):
    REPLY = "reply"              # the destination answered
    TTL_EXPIRED = "ttl_expired"  # a router on the way answered "time exceeded"
    TIMEOUT = "timeout"          # nobody answered in time
    UNREACHABLE = "unreachable"  # someone answered "destination unreachable"
    ERROR = "error"              # the probe couldn't be sent, or failed oddly

    @property
    def answered(self) -> bool:
        """Did anyone send something back (and so give us a round-trip time)?"""
        return self in (ProbeStatus.REPLY, ProbeStatus.TTL_EXPIRED, ProbeStatus.UNREACHABLE)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    target: str              # the address probed
    ttl: int
    status: ProbeStatus
    responder: str | None    # the address that answered, if anyone did
    rtt_ms: float | None     # set whenever status.answered
    sent_at: float           # time.time() when the probe went out
    detail: str = ""         # human-readable reason for ERROR / UNREACHABLE


@dataclass(slots=True)
class PingTarget:
    """One host being pinged: what the user typed, what it resolved to, how it's doing."""

    name: str
    address: str | None = None
    stats: RollingStats = field(default_factory=RollingStats)
    error: str | None = None
    last_status: ProbeStatus | None = None


@dataclass(slots=True)
class Hop:
    """One TTL of a traced route. Load balancing can put several routers on one hop."""

    ttl: int
    stats: RollingStats = field(default_factory=RollingStats)
    responders: Counter[str] = field(default_factory=Counter)
    last_responder: str | None = None
    last_status: ProbeStatus | None = None

    @property
    def address(self) -> str | None:
        """The router that has answered most often at this hop."""
        if not self.responders:
            return None
        return self.responders.most_common(1)[0][0]
