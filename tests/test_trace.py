import asyncio

import pytest

from ndpt.core.backends.fake import DemoResolver, FakeHop, FakeProber, demo_route
from ndpt.core.backends.tcp import TcpProber
from ndpt.core.models import ProbeStatus
from ndpt.core.trace import TraceSession
from tests.helpers import StubResolver

DEST = "203.0.113.9"
FAST = dict(interval=0.001, timeout=0.5, stagger=0.0, lookup_names=False)


def five_hops() -> list[FakeHop]:
    return [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.2", 5.0), FakeHop(None),
            FakeHop("192.0.2.4", 12.0), FakeHop(DEST, 15.0)]


async def test_finds_each_hop_and_the_destination():
    session = TraceSession(DEST, FakeProber({DEST: five_hops()}), rounds=3, **FAST)
    await session.run()
    hops = session.visible_hops
    assert session.dest_ttl == 5
    assert [h.address for h in hops] == ["192.168.1.1", "192.0.2.2", None, "192.0.2.4", DEST]
    assert [h.stats.sent for h in hops] == [3] * 5
    assert hops[2].stats.loss_pct == 100.0
    assert hops[1].last_status is ProbeStatus.TTL_EXPIRED
    assert hops[4].last_status is ProbeStatus.REPLY
    assert hops[3].stats.avg == pytest.approx(12.0)
    assert session.events == [f"reached {DEST} at hop 5"]


async def test_discovery_stops_sending_once_the_destination_answers():
    prober = FakeProber({DEST: five_hops()})
    session = TraceSession(DEST, prober, rounds=1, interval=0.001, timeout=0.5, stagger=0.001,
                           lookup_names=False)
    await session.run()
    assert max(ttl for _, ttl in prober.probes) <= 6


async def test_later_rounds_probe_only_up_to_the_destination():
    prober = FakeProber({DEST: five_hops()})
    session = TraceSession(DEST, prober, rounds=3, max_hops=10, **FAST)
    await session.run()
    later = prober.probes[10:]  # round 1 sent all 10 at once (no stagger)
    assert sorted(ttl for _, ttl in later) == sorted([1, 2, 3, 4, 5] * 2)


async def test_load_balanced_hop_lists_every_router():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop(("192.0.2.2", "192.0.2.3"), 5.0), FakeHop(DEST, 9.0)]
    session = TraceSession(DEST, FakeProber({DEST: route}), rounds=4, **FAST)
    await session.run()
    hop = session.visible_hops[1]
    assert set(hop.responders) == {"192.0.2.2", "192.0.2.3"}
    assert "hop 2: also answered by 192.0.2.3" in session.events


async def test_unreachable_ends_the_route():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.2", 5.0, status=ProbeStatus.UNREACHABLE)]
    session = TraceSession(DEST, FakeProber({DEST: route}), rounds=2, **FAST)
    await session.run()
    assert session.dest_ttl == 2
    assert len(session.visible_hops) == 2
    assert session.events == ["hop 2 (192.0.2.2) says unreachable"]


async def test_silent_destination_shows_one_hop_past_the_last_answer():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.2", 5.0), FakeHop(None)]
    session = TraceSession(DEST, FakeProber({DEST: route}), rounds=2, max_hops=8, **FAST)
    await session.run()
    assert session.dest_ttl is None
    assert [h.ttl for h in session.visible_hops] == [1, 2, 3]
    assert all(h.stats.sent == 2 for h in session.hops)  # still probing every TTL


async def test_a_longer_path_sends_it_looking_for_the_destination_again():
    prober = FakeProber({DEST: [FakeHop("192.168.1.1", 1.0), FakeHop(DEST, 5.0)]})
    longer = [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.7", 3.0), FakeHop(DEST, 5.0)]
    session = TraceSession(DEST, prober, rounds=4, max_hops=6, **FAST)

    def reroute(hop, result):
        if session.round >= 2:
            prober.routes[DEST] = longer

    session.listeners.append(reroute)
    await session.run()
    assert session.dest_ttl == 3
    assert set(session.visible_hops[1].responders) == {DEST, "192.0.2.7"}
    assert session.events == [
        f"reached {DEST} at hop 2",
        "hop 2 is a router now, not the destination: the path got longer",
        "hop 2: also answered by 192.0.2.7",
        "destination now at hop 3",
    ]


async def test_notes_explain_loss_and_delay_that_do_not_carry_on():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.2", rtts=[40.0, None]),
             FakeHop("192.0.2.3", 8.0), FakeHop(DEST, 10.0)]
    session = TraceSession(DEST, FakeProber({DEST: route}), rounds=12, **FAST)
    await session.run()
    notes = session.notes()
    assert any(n.startswith("hop 2:") and "rate-limiting" in n for n in notes)
    assert any(n.startswith("hop 2:") and "slow to reply" in n for n in notes)
    assert all(n.startswith("hop 2:") for n in notes)


async def test_no_notes_when_the_loss_carries_through_to_the_destination():
    route = [FakeHop("192.168.1.1", 1.0), FakeHop("192.0.2.2", rtts=[5.0, None]),
             FakeHop(DEST, rtts=[9.0, None])]
    session = TraceSession(DEST, FakeProber({DEST: route}), rounds=12, **FAST)
    await session.run()
    assert session.notes() == []


async def test_looks_up_hop_names_in_the_background():
    session = TraceSession(DEST, FakeProber({DEST: five_hops()}), resolver=DemoResolver(), rounds=1,
                           interval=0.001, timeout=0.5, stagger=0.0)
    await session.run()
    assert session.resolver.cached("192.0.2.2") == "r192-0-2-2.demo.invalid"


async def test_an_unresolvable_host_is_an_error_not_a_crash():
    session = TraceSession("nowhere.example", FakeProber(), resolver=StubResolver(), rounds=1, **FAST)
    await session.run()
    assert "can't resolve" in session.error
    assert session.hops == []


def test_a_tcp_prober_cannot_trace():
    with pytest.raises(ValueError, match="can't trace"):
        TraceSession(DEST, TcpProber())


def test_demo_routes_are_stable_and_end_at_the_destination():
    assert demo_route(DEST) == demo_route(DEST)
    assert demo_route(DEST)[-1].address == DEST


async def test_pause_holds_the_rounds_until_resumed():
    session = TraceSession(DEST, FakeProber({DEST: five_hops()}), interval=0.02, timeout=0.5,
                           stagger=0.0, lookup_names=False)
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.07)
    session.pause()
    await asyncio.sleep(0.03)
    rounds = session.round
    await asyncio.sleep(0.1)
    assert session.round == rounds
    session.resume()
    await asyncio.sleep(0.07)
    assert session.round > rounds
    session.stop()
    await asyncio.wait_for(task, 1.0)


async def test_cancelling_run_drops_the_probes_in_flight():
    route = [FakeHop("192.168.1.1", 100.0), FakeHop(DEST, 100.0)]
    session = TraceSession(DEST, FakeProber({DEST: route}, time_scale=1.0), interval=0.01,
                           timeout=1.0, stagger=0.0, lookup_names=False)
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0.15)
    assert all(hop.stats.sent == 0 for hop in session.hops)
