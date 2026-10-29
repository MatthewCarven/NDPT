import asyncio
import time

import pytest

from ndpt.core.backends.fake import FakeHop, FakeProber
from ndpt.core.models import ProbeStatus
from ndpt.core.ping import PingSession
from tests.helpers import StubResolver

HOST = "192.0.2.1"
FAST = dict(interval=0.001, timeout=0.5)


def prober_for(*hops: FakeHop, host: str = HOST, **kwargs) -> FakeProber:
    return FakeProber({host: list(hops)}, **kwargs)


async def test_counts_replies_and_losses():
    prober = prober_for(FakeHop(HOST, rtts=[10.0, None, 30.0, 20.0, None]))
    session = PingSession([HOST], prober, count=5, **FAST)
    await session.run()
    target = session.targets[0]
    assert target.address == HOST
    assert (target.stats.sent, target.stats.received) == (5, 3)
    assert target.stats.avg == pytest.approx(20.0)
    assert target.last_status is ProbeStatus.TIMEOUT
    assert prober.probes == [(HOST, 64)] * 5


async def test_pings_several_hosts_and_reports_the_unresolvable():
    routes = {"192.0.2.1": [FakeHop("192.0.2.1", 5.0)], "192.0.2.2": [FakeHop("192.0.2.2", 50.0)]}
    session = PingSession(["192.0.2.1", "far.example", "nowhere.example"], FakeProber(routes),
                          resolver=StubResolver({"far.example": "192.0.2.2"}), count=3, **FAST)
    await session.run()
    near, far, nowhere = session.targets
    assert near.stats.received == 3 and near.stats.avg == pytest.approx(5.0)
    assert far.address == "192.0.2.2" and far.stats.avg == pytest.approx(50.0)
    assert nowhere.address is None and "can't resolve" in nowhere.error


async def test_listeners_hear_every_result():
    seen = []
    session = PingSession([HOST], prober_for(FakeHop(HOST, 1.0)), count=4, **FAST)
    session.listeners.append(lambda target, result: seen.append((target.name, result.status)))
    await session.run()
    assert seen == [(HOST, ProbeStatus.REPLY)] * 4


async def test_a_failing_listener_does_not_stop_the_session():
    session = PingSession([HOST], prober_for(FakeHop(HOST, 1.0)), count=3, **FAST)
    session.listeners.append(lambda target, result: 1 / 0)
    await session.run()
    assert session.targets[0].stats.sent == 3


async def test_a_prober_crash_becomes_an_error_result():
    class Broken(FakeProber):
        async def probe(self, dest, **kwargs):
            raise RuntimeError("boom")

    session = PingSession([HOST], Broken(), count=2, **FAST)
    await session.run()
    target = session.targets[0]
    assert (target.stats.sent, target.stats.received) == (2, 0)
    assert target.last_status is ProbeStatus.ERROR


async def test_stop_ends_an_endless_session():
    session = PingSession([HOST], prober_for(FakeHop(HOST, 1.0)), interval=0.01, timeout=0.5)
    task = asyncio.create_task(session.run())
    await asyncio.sleep(0.1)
    session.stop()
    await asyncio.wait_for(task, 1.0)
    assert 3 <= session.targets[0].stats.sent <= 20


async def test_keeps_a_steady_beat_while_answers_are_slow():
    # Answers take 100 ms but the beat is 20 ms: probes overlap instead of queueing.
    prober = prober_for(FakeHop(HOST, 100.0), time_scale=1.0)
    session = PingSession([HOST], prober, interval=0.02, timeout=1.0, count=5)
    start = time.perf_counter()
    await session.run()
    assert session.targets[0].stats.received == 5
    assert time.perf_counter() - start < 0.4  # ~0.08 s of beats + one 0.1 s answer, not 5 x 0.1 s


def test_rejects_bad_settings():
    with pytest.raises(ValueError):
        PingSession([], FakeProber())
    with pytest.raises(ValueError):
        PingSession([HOST], FakeProber(), interval=0)
    with pytest.raises(ValueError):
        PingSession([HOST], FakeProber(), size=70000)
    with pytest.raises(ValueError):
        PingSession([HOST], FakeProber(), count=0)
