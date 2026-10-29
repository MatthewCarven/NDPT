import asyncio
import socket
import threading
import time

import pytest

from ndpt.core.backends.fake import FakeHop, FakeProber
from ndpt.core.ping import PingSession
from ndpt.core.resolve import Resolver, ResolveError
from ndpt.core.runner import LoopThread


async def test_ip_literals_pass_through_without_dns():
    resolver = Resolver()
    assert await resolver.resolve("192.0.2.1") == "192.0.2.1"
    assert await resolver.resolve("::1") == "::1"


async def test_an_address_of_the_wrong_family_is_refused():
    with pytest.raises(ResolveError):
        await Resolver().resolve("::1", socket.AF_INET)


async def test_resolves_localhost():
    assert await Resolver().resolve("localhost", socket.AF_INET) == "127.0.0.1"


async def test_reverse_lookups_are_shared_and_cached(monkeypatch):
    calls = []

    async def fake_getnameinfo(sockaddr, flags=0):
        calls.append(sockaddr)
        await asyncio.sleep(0.01)
        return "router.example", "0"

    monkeypatch.setattr(asyncio.get_running_loop(), "getnameinfo", fake_getnameinfo)
    resolver = Resolver()
    assert resolver.cached("192.0.2.1") is None
    names = await asyncio.gather(resolver.reverse("192.0.2.1"), resolver.reverse("192.0.2.1"))
    assert names == ["router.example", "router.example"]
    assert await resolver.reverse("192.0.2.1") == "router.example"
    assert resolver.cached("192.0.2.1") == "router.example"
    assert len(calls) == 1


async def test_an_address_with_no_name_reverses_to_none(monkeypatch):
    async def no_name(sockaddr, flags=0):
        raise socket.gaierror(11001, "host not found")

    monkeypatch.setattr(asyncio.get_running_loop(), "getnameinfo", no_name)
    assert await Resolver().reverse("192.0.2.1") is None


def test_loop_thread_runs_coroutines_on_its_own_thread():
    async def where():
        return threading.current_thread().name

    with LoopThread() as runner:
        assert runner.submit(where()).result(timeout=2) == "ndpt-loop"


def test_loop_thread_drives_a_session_stopped_from_another_thread():
    session = PingSession(["192.0.2.1"], FakeProber({"192.0.2.1": [FakeHop("192.0.2.1", 1.0)]}),
                          interval=0.01, timeout=0.5)
    with LoopThread() as runner:
        finished = runner.submit(session.run())
        time.sleep(0.1)
        runner.call(session.stop)
        finished.result(timeout=2)
    assert session.targets[0].stats.sent >= 3
