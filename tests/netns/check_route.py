"""Probe the little network that route.sh builds, and check every kind of answer.

    python check_route.py raw|ping

The argument says which sockets the prober should have chosen: raw (root) or
ping sockets (an ordinary user). Exits 1 if anything came back wrong.
"""

import asyncio
import sys

from ndpt.core.backends.posix_icmp import PosixIcmpProber
from ndpt.core.models import ProbeStatus
from ndpt.core.trace import TraceSession

REPLY, EXPIRED, UNREACHABLE = ProbeStatus.REPLY, ProbeStatus.TTL_EXPIRED, ProbeStatus.UNREACHABLE
CASES = [  # where to, with what TTL, what should come back, and from whom
    ("10.1.0.1", 64, REPLY, "10.1.0.1", ""),
    ("10.2.0.2", 1, EXPIRED, "10.1.0.1", ""),
    ("10.2.0.2", 2, REPLY, "10.2.0.2", ""),
    ("10.9.0.9", 64, UNREACHABLE, "10.1.0.1", "network unreachable"),  # no route at the router
    ("fd00:1::1", 64, REPLY, "fd00:1::1", ""),
    ("fd00:2::2", 1, EXPIRED, "fd00:1::1", ""),
    ("fd00:2::2", 2, REPLY, "fd00:2::2", ""),
    ("fd00:9::9", 64, UNREACHABLE, "fd00:1::1", "no route"),
]


async def main(mode: str) -> int:
    prober = PosixIcmpProber()
    using = "raw" if prober.raw else "ping"
    bad = using != mode
    print(f"{'ok ' if not bad else 'BAD'} sockets: {using} (wanted {mode})")
    # The unreachable ones first: Linux sends "no route" (ip_error) only when the router's
    # tokens for the client allow, and every "time exceeded" (with icmp_ratelimit=0) zeroes
    # them. Then the rest all at once, as a trace sends them.
    first = [case for case in CASES if case[2] is UNREACHABLE]
    rest = [case for case in CASES if case[2] is not UNREACHABLE]
    results = await asyncio.gather(*(prober.probe(dest, ttl=ttl, timeout=2) for dest, ttl, *_ in first))
    results += await asyncio.gather(*(prober.probe(dest, ttl=ttl, timeout=2) for dest, ttl, *_ in rest))
    for (dest, ttl, status, responder, detail), r in zip(first + rest, results):
        ok = r.status is status and r.responder == responder and r.detail == detail
        rtt = f"{r.rtt_ms:.3f} ms" if r.rtt_ms is not None else "-"
        print(f"{'ok ' if ok else 'BAD'} {dest} ttl {ttl}: {r.status.value} from {r.responder}, "
              f"{rtt} {r.detail}")
        bad |= not ok
    for dest, route in (("10.2.0.2", ["10.1.0.1", "10.2.0.2"]), ("fd00:2::2", ["fd00:1::1", "fd00:2::2"])):
        session = TraceSession(dest, prober, rounds=3, interval=0.1, timeout=1, lookup_names=False)
        await session.run()
        found = [hop.address for hop in session.visible_hops]
        ok = found == route and all(hop.stats.loss_pct == 0 for hop in session.visible_hops)
        print(f"{'ok ' if ok else 'BAD'} trace {dest}: {found}, "
              f"loss {[hop.stats.loss_pct for hop in session.visible_hops]}")
        bad |= not ok
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1])))
