import asyncio

import pytest

from ndpt.core.backends.tcp import TcpProber
from ndpt.core.backends.win_icmp import _payload, classify, combine_rtt
from ndpt.core.models import ProbeStatus
from tests.helpers import windows_only

S = ProbeStatus


@pytest.mark.parametrize("code, status", [
    (0, S.REPLY), (11013, S.TTL_EXPIRED), (11041, S.TTL_EXPIRED), (11010, S.TIMEOUT),
    (11002, S.UNREACHABLE), (11003, S.UNREACHABLE), (11014, S.ERROR), (11050, S.ERROR),
])
def test_classify_maps_icmp_status_codes(code, status):
    assert classify(code)[0] is status


def test_classify_says_why_a_host_is_unreachable():
    assert classify(11003) == (S.UNREACHABLE, "host unreachable")


@pytest.mark.parametrize("api, wall, expected", [
    (0, 0.61, 0.61),    # LAN hop: the API says 0, our clock knows better
    (26, 27.11, 27.0),  # our clock ran long (thread scheduling): cap at the API's millisecond
    (26, 25.0, 26.0),   # never below what the API measured
])
def test_combine_rtt_keeps_our_clock_within_the_apis_millisecond(api, wall, expected):
    assert combine_rtt(api, wall) == pytest.approx(expected)


def test_payload_is_the_size_asked_for():
    assert _payload(0) == b""
    assert len(_payload(32)) == 32
    assert len(_payload(1000)) == 1000


@windows_only
@pytest.mark.network
async def test_icmp_pings_ipv4_loopback():
    from ndpt.core.backends.win_icmp import WinIcmpProber
    async with WinIcmpProber() as prober:
        result = await prober.probe("127.0.0.1", timeout=1.0)
    assert result.status is S.REPLY
    assert result.responder == "127.0.0.1"
    assert 0 <= result.rtt_ms < 50


@windows_only
@pytest.mark.network
async def test_icmp_pings_ipv6_loopback():
    from ndpt.core.backends.win_icmp import WinIcmpProber
    async with WinIcmpProber() as prober:
        result = await prober.probe("::1", timeout=1.0)
    assert result.status is S.REPLY
    assert result.responder == "::1"


@windows_only
@pytest.mark.network
async def test_icmp_reports_parallel_loopback_probes_separately():
    from ndpt.core.backends.win_icmp import WinIcmpProber
    async with WinIcmpProber() as prober:
        results = await asyncio.gather(*(prober.probe("127.0.0.1", size=n) for n in range(16)))
    assert all(r.status is S.REPLY for r in results)


@windows_only
@pytest.mark.network
async def test_icmp_to_an_unrouted_address_gets_no_reply():
    from ndpt.core.backends.win_icmp import WinIcmpProber
    async with WinIcmpProber() as prober:
        result = await prober.probe("192.0.2.1", timeout=0.3)  # TEST-NET-1: never routed
    assert result.status is not S.REPLY
    assert result.rtt_ms is None or result.status is S.UNREACHABLE


@pytest.mark.network
async def test_tcp_times_a_handshake_to_an_open_port():
    server = await asyncio.start_server(lambda reader, writer: writer.close(), "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with server:
        result = await TcpProber(port).probe("127.0.0.1", timeout=2.0)
    assert result.status is S.REPLY
    assert result.responder == "127.0.0.1"
    assert 0 <= result.rtt_ms < 1000


@pytest.mark.network
async def test_tcp_times_out_when_nobody_answers():
    result = await TcpProber(443).probe("192.0.2.1", timeout=0.2)
    assert result.status in (S.TIMEOUT, S.ERROR)
    assert result.rtt_ms is None
