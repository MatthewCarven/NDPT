import asyncio
import errno
import os
import socket
import struct
import sys

import pytest

from ndpt.core.backends.posix_icmp import (IP_RECVERR, IPV6_RECVERR, SO_EE_ORIGIN_ICMP,
                                           SO_EE_ORIGIN_ICMP6, SO_EE_ORIGIN_LOCAL, Heard,
                                           checksum, echo_request, no_ping_sockets,
                                           parse_error_queue, parse_packet, payload)
from ndpt.core.models import ProbeStatus

DEST, ROUTER = "203.0.113.9", "192.0.2.1"
DEST6, ROUTER6 = "2001:db8::9", "2001:db8::1"


def ipv4_header(src: str, dst: str, length: int, proto: int = socket.IPPROTO_ICMP) -> bytes:
    return struct.pack("!BBHHHBBH4s4s", 0x45, 0, 20 + length, 0, 0, 64, proto, 0,
                       socket.inet_aton(src), socket.inet_aton(dst))


def ipv6_header(src: str, dst: str, length: int, next_header: int = socket.IPPROTO_ICMPV6) -> bytes:
    return struct.pack("!IHBB16s16s", 6 << 28, length, next_header, 64,
                       socket.inet_pton(socket.AF_INET6, src), socket.inet_pton(socket.AF_INET6, dst))


def icmp_error(kind: int, code: int, quoted: bytes) -> bytes:
    return struct.pack("!BBHI", kind, code, 0, 0) + quoted


def test_an_echo_request_carries_a_valid_checksum():
    packet = echo_request(0x1234, 7, payload(32), v6=False)
    assert packet[0] == 8 and struct.unpack("!HH", packet[4:8]) == (0x1234, 7)
    assert checksum(packet) == 0  # a packet summed with its own checksum comes to zero
    assert checksum(echo_request(1, 2, payload(5), v6=False)) == 0  # odd lengths too
    assert payload(25) == b"abcdefghijklmnopqrstuvwab"


def test_an_icmpv6_echo_request_leaves_the_checksum_to_the_kernel():
    packet = echo_request(0x1234, 7, b"", v6=True)
    assert packet == struct.pack("!BBHHH", 128, 0, 0, 0x1234, 7)


def test_a_reply_parses_with_or_without_its_ip_header():
    reply = struct.pack("!BBHHH", 0, 0, 0, 0x1234, 7) + payload(32)
    expected = Heard(ProbeStatus.REPLY, "", 0x1234, 7, None)
    assert parse_packet(reply, v6=False) == expected                                     # a Linux ping socket
    assert parse_packet(ipv4_header(DEST, "10.0.0.2", len(reply)) + reply, v6=False) == expected  # macOS, raw
    assert parse_packet(struct.pack("!BBHHH", 129, 0, 0, 0x1234, 7), v6=True) == expected


def test_an_icmp_error_names_the_probe_it_quotes():
    probe = echo_request(0x1234, 7, payload(32), v6=False)
    quoted = ipv4_header("10.0.0.2", DEST, len(probe)) + probe[:8]  # routers quote at least 8 bytes
    error = icmp_error(11, 0, quoted)
    heard = parse_packet(ipv4_header(ROUTER, "10.0.0.2", len(error)) + error, v6=False)
    assert heard == Heard(ProbeStatus.TTL_EXPIRED, "", 0x1234, 7, DEST)
    assert parse_packet(icmp_error(3, 1, quoted), v6=False).detail == "host unreachable"
    assert parse_packet(icmp_error(3, 13, quoted), v6=False).detail == "administratively prohibited"
    too_big = parse_packet(icmp_error(3, 4, quoted), v6=False)
    assert too_big.status is ProbeStatus.ERROR and too_big.detail == "packet too big"


def test_an_icmpv6_error_names_the_probe_it_quotes():
    probe = echo_request(0x1234, 7, b"", v6=True)
    quoted = ipv6_header("2001:db8::2", DEST6, len(probe)) + probe
    assert parse_packet(icmp_error(3, 0, quoted), v6=True) == \
        Heard(ProbeStatus.TTL_EXPIRED, "", 0x1234, 7, DEST6)
    unreachable = parse_packet(icmp_error(1, 3, quoted), v6=True)
    assert unreachable.status is ProbeStatus.UNREACHABLE and unreachable.detail == "address unreachable"
    assert parse_packet(icmp_error(2, 0, quoted), v6=True).status is ProbeStatus.ERROR


def test_packets_that_arent_about_an_echo_request_are_ignored():
    probe = echo_request(0x1234, 7, b"", v6=False)
    assert parse_packet(probe, v6=False) is None  # a raw socket hears our own requests too
    udp = ipv4_header("10.0.0.2", DEST, 8, proto=socket.IPPROTO_UDP) + bytes(8)
    assert parse_packet(icmp_error(11, 0, udp), v6=False) is None  # someone's traceroute
    assert parse_packet(struct.pack("!BBHI", 5, 0, 0, 0), v6=False) is None  # a redirect
    assert parse_packet(struct.pack("!BBHI", 135, 0, 0, 0), v6=True) is None  # neighbour solicitation
    assert parse_packet(b"\0\0\0", v6=False) is None


def extended_err(origin: int, kind: int, code: int, err: int = errno.EHOSTUNREACH) -> bytes:
    return struct.pack("=IBBBBII", err, origin, kind, code, 0, 0, 0)


def test_a_linux_error_queue_entry_says_who_answered_and_which_probe():
    quoted = echo_request(0x4321, 7, b"", v6=False)  # what the router quoted of our probe
    sender = struct.pack("=HH4s8x", socket.AF_INET, 0, socket.inet_aton(ROUTER))
    cmsg = [(socket.IPPROTO_IP, IP_RECVERR, extended_err(SO_EE_ORIGIN_ICMP, 11, 0) + sender)]
    assert parse_error_queue(quoted, cmsg, v6=False) == (ProbeStatus.TTL_EXPIRED, "", ROUTER, 7)

    sender6 = struct.pack("=HHI16sI", socket.AF_INET6, 0, 0, socket.inet_pton(socket.AF_INET6, ROUTER6), 0)
    cmsg6 = [(socket.IPPROTO_IPV6, IPV6_RECVERR, extended_err(SO_EE_ORIGIN_ICMP6, 1, 3) + sender6)]
    assert parse_error_queue(quoted, cmsg6, v6=True) == \
        (ProbeStatus.UNREACHABLE, "address unreachable", ROUTER6, 7)


def test_a_local_error_on_the_queue_is_an_error_with_its_reason():
    cmsg = [(socket.IPPROTO_IP, IP_RECVERR, extended_err(SO_EE_ORIGIN_LOCAL, 0, 0, errno.EMSGSIZE))]
    assert parse_error_queue(b"", cmsg, v6=False) == \
        (ProbeStatus.ERROR, os.strerror(errno.EMSGSIZE), None, None)
    assert parse_error_queue(b"", [(socket.IPPROTO_IP, 99, b"")], v6=False) is None


def test_built_programs_dont_suggest_setcap():
    # A one-file build won't start with a capability (PyInstaller can't read its parent's
    # /proc entry), so only running from source offers it.
    assert "setcap" in no_ping_sockets(built=False)
    assert "setcap" not in no_ping_sockets(built=True)
    assert "ping_group_range" in no_ping_sockets(built=True)
    assert no_ping_sockets() == no_ping_sockets(built=False)  # the tests run from source


posix_only = pytest.mark.skipif(sys.platform == "win32", reason="the Windows prober is used there")


def prober_or_skip():
    from ndpt.core.backends.posix_icmp import PosixIcmpProber
    try:
        return PosixIcmpProber()
    except PermissionError as e:
        pytest.skip(str(e))


@pytest.mark.network
@posix_only
async def test_pings_localhost():
    prober = prober_or_skip()
    results = await asyncio.gather(*(prober.probe("127.0.0.1", timeout=2) for _ in range(5)))
    assert all(r.status is ProbeStatus.REPLY and r.responder == "127.0.0.1" for r in results)
    assert all(0 <= r.rtt_ms < 100 for r in results)


@pytest.mark.network
@posix_only
async def test_pings_localhost_over_ipv6():
    if not socket.has_ipv6:
        pytest.skip("no IPv6")
    prober = prober_or_skip()
    result = await prober.probe("::1", timeout=2)
    if result.status is ProbeStatus.ERROR:
        pytest.skip(f"no IPv6 loopback here: {result.detail}")
    assert result.status is ProbeStatus.REPLY and result.responder == "::1"
