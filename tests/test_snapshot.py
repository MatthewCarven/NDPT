import dataclasses

import pytest

from ndpt.core.backends.fake import DemoResolver, FakeHop, FakeProber
from ndpt.core.ping import PingSession
from ndpt.core.snapshot import HopSnapshot, Responder, StatsSnapshot, carried_on
from ndpt.core.stats import RollingStats
from ndpt.core.trace import TraceSession

DEST = "203.0.113.9"


async def test_a_ping_snapshot_is_a_frozen_copy():
    prober = FakeProber({"192.0.2.1": [FakeHop("192.0.2.1", rtts=[2.0, 4.0, None])]})
    session = PingSession(["192.0.2.1"], prober, interval=0.001, timeout=0.5, count=6)
    await session.run()
    snap = session.snapshot()
    target = snap.targets[0]
    s = target.stats
    assert (s.sent, s.received, s.lost) == (6, 4, 2)
    assert s.loss_pct == pytest.approx(100 * 2 / 6)
    assert (s.best, s.worst, s.avg, s.last) == (2.0, 4.0, 3.0, 4.0)
    assert [rtt for _, rtt in s.history] == [2.0, 4.0, None] * 2
    assert target.key == id(session.targets[0]) and target.address == "192.0.2.1"
    assert snap.prober == "fake" and not snap.paused
    with pytest.raises(dataclasses.FrozenInstanceError):
        s.sent = 0
    session.targets[0].stats.add(9.0)  # the session moves on; the snapshot doesn't
    assert s.sent == 6 and len(s.history) == 6


def test_jitter_waits_for_two_answers():
    stats = RollingStats()
    stats.add(5.0)
    assert StatsSnapshot.of(stats).jitter is None
    stats.add(7.0)
    assert StatsSnapshot.of(stats).jitter == pytest.approx(2 / 16)


async def test_a_trace_snapshot_has_the_visible_hops_with_their_names():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop(("192.0.2.2", "192.0.2.3", "192.0.2.2"), 5.0),
             FakeHop(DEST, 9.0)]
    session = TraceSession(DEST, FakeProber({DEST: route}), resolver=DemoResolver(), rounds=6,
                           interval=0.001, timeout=0.5, stagger=0.0)
    await session.run()
    snap = session.snapshot()
    assert snap.dest_ttl == 3 and snap.round == 6 and snap.address == DEST
    assert [h.ttl for h in snap.hops] == [1, 2, 3]
    balanced = snap.hops[1]
    assert balanced.responders == (Responder("192.0.2.2", 4, "r192-0-2-2.demo.invalid"),
                                   Responder("192.0.2.3", 2, "r192-0-2-3.demo.invalid"))
    assert balanced.address == "192.0.2.2" and balanced.name == "r192-0-2-2.demo.invalid"
    assert snap.events == (f"reached {DEST} at hop 3", "hop 2: also answered by 192.0.2.3")
    assert snap.notes == ()


def hop(ttl: int, rtts: list[float | None]) -> HopSnapshot:
    stats = RollingStats()
    for rtt in rtts:
        stats.add(rtt)
    return HopSnapshot(ttl, (Responder(f"192.0.2.{ttl}", 1, None),) if stats.received else (),
                       None, StatsSnapshot.of(stats))


def test_loss_and_delay_that_stop_at_a_hop_dont_carry_on():
    hops = [hop(1, [1.0] * 10),
            hop(2, [40.0, None] * 5),      # slow and lossy, but only here: rate-limited replies
            hop(3, [None] * 10),           # never answers: says nothing either way
            hop(4, [12.0] * 9 + [None]),   # the destination: 10% loss, and that's real
            ]
    carried = carried_on(hops)
    assert [c.loss_pct for c in carried] == [0.0, 10.0, None, 10.0]
    assert [c.avg for c in carried] == [1.0, 12.0, None, 12.0]
    assert [c.loss_stops_here for c in carried] == [False, True, False, False]
    assert [c.slow_to_reply for c in carried] == [False, True, False, False]


def test_what_carries_on_is_never_more_than_the_hop_shows():
    hops = [hop(1, [5.0, None, 5.0, 5.0]), hop(2, [3.0] * 3 + [None] * 3)]
    carried = carried_on(hops)
    assert carried[0].loss_pct == 25.0   # less than the destination's 50%: only its own counts
    assert carried[0].avg == 3.0         # but the hop after it answers faster
