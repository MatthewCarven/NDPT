"""ICMP echo through ordinary sockets, for Linux and macOS.

Neither needs root for it. Both have "ping sockets" (SOCK_DGRAM with
IPPROTO_ICMP), which let a user send echo requests with any TTL: macOS for
everyone, Linux for the groups in net.ipv4.ping_group_range (most
distributions open it to all; WSL and some minimal systems leave it shut).
Failing that, a raw socket works for root, or for a program given CAP_NET_RAW
(but not one built by packaging/build.py: see NO_PING_SOCKETS_BUILT).

The two kernels hand back "time exceeded" differently. macOS, and any raw
socket, deliver the ICMP error as a packet like any other, quoting the start
of the probe it's about. A Linux ping socket keeps the error on the socket's
error queue (IP_RECVERR), with the router that sent it. Either way each probe
gets a socket of its own, so concurrent probes share nothing.
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import random
import socket
import struct
import sys
import time
from dataclasses import dataclass

from ndpt.core.backends.base import Prober
from ndpt.core.models import ProbeResult, ProbeStatus

ICMP_ECHO_REPLY, ICMP_UNREACH, ICMP_ECHO, ICMP_TIME_EXCEEDED = 0, 3, 8, 11
ICMP6_UNREACH, ICMP6_PACKET_TOO_BIG, ICMP6_TIME_EXCEEDED = 1, 2, 3
ICMP6_ECHO, ICMP6_ECHO_REPLY = 128, 129

_UNREACH4 = {0: "network unreachable", 1: "host unreachable", 2: "protocol unreachable",
             3: "port unreachable", 5: "source route failed", 6: "network unknown",
             7: "host unknown", 9: "network prohibited", 10: "host prohibited",
             11: "network unreachable for TOS", 12: "host unreachable for TOS",
             13: "administratively prohibited"}
_UNREACH6 = {0: "no route", 1: "administratively prohibited", 2: "beyond scope of source address",
             3: "address unreachable", 4: "port unreachable", 5: "source address failed policy",
             6: "reject route"}

# Linux's error queue (linux/errqueue.h). Python names these on Linux only, and not all of them.
MSG_ERRQUEUE = getattr(socket, "MSG_ERRQUEUE", 0x2000)
IP_RECVERR = getattr(socket, "IP_RECVERR", 11)
IPV6_RECVERR = getattr(socket, "IPV6_RECVERR", 25)
SO_EE_ORIGIN_LOCAL, SO_EE_ORIGIN_ICMP, SO_EE_ORIGIN_ICMP6 = 1, 2, 3
_EXTENDED_ERR = struct.Struct("=IBBBBII")  # struct sock_extended_err; the sender's address follows

_PAYLOAD = b"abcdefghijklmnopqrstuvw"  # what Windows ping sends, as the Windows prober does

NO_PING_SOCKETS = (
    "sending pings here needs one of: ping sockets for your group "
    "(sudo sysctl -w net.ipv4.ping_group_range=\"0 2147483647\"), root, or CAP_NET_RAW "
    "for this program (sudo setcap cap_net_raw+ep PROGRAM)")
# A one-file program (packaging/build.py) won't start with a capability: Linux makes it
# undumpable, and the unpacked child can no longer read its parent's /proc entry, which
# PyInstaller checks. So the built programs don't offer setcap.
NO_PING_SOCKETS_BUILT = (
    "sending pings here needs ping sockets for your group "
    "(sudo sysctl -w net.ipv4.ping_group_range=\"0 2147483647\"), or root (sudo)")


def no_ping_sockets(built: bool | None = None) -> str:
    """What to change, for running from source or as a built program (PyInstaller's)."""
    if built is None:
        built = getattr(sys, "frozen", False)
    return NO_PING_SOCKETS_BUILT if built else NO_PING_SOCKETS


def error_status(kind: int, code: int, v6: bool) -> tuple[ProbeStatus | None, str]:
    """What an ICMP error type and code mean for a probe, or None if it isn't one we follow.

    "Packet too big" is an error rather than an answer, as on Windows.
    """
    if v6:
        if kind == ICMP6_TIME_EXCEEDED:
            return ProbeStatus.TTL_EXPIRED, ""
        if kind == ICMP6_UNREACH:
            return ProbeStatus.UNREACHABLE, _UNREACH6.get(code, f"unreachable (code {code})")
        if kind == ICMP6_PACKET_TOO_BIG:
            return ProbeStatus.ERROR, "packet too big"
        return None, ""
    if kind == ICMP_TIME_EXCEEDED:
        return ProbeStatus.TTL_EXPIRED, ""
    if kind == ICMP_UNREACH:
        if code == 4:
            return ProbeStatus.ERROR, "packet too big"
        return ProbeStatus.UNREACHABLE, _UNREACH4.get(code, f"unreachable (code {code})")
    return None, ""


def checksum(data: bytes) -> int:
    """The Internet checksum (RFC 1071)."""
    if len(data) % 2:
        data += b"\0"
    total = sum(struct.unpack(f"!{len(data) // 2}H", data))
    while total >> 16:
        total = (total & 0xFFFF) + (total >> 16)
    return ~total & 0xFFFF


def payload(size: int) -> bytes:
    return (_PAYLOAD * (size // len(_PAYLOAD) + 1))[:size]


def echo_request(ident: int, seq: int, data: bytes, v6: bool) -> bytes:
    """An echo request. The kernel fills in an ICMPv6 checksum itself, and a Linux ping socket
    rewrites the identifier (and so the checksum) of either."""
    kind = ICMP6_ECHO if v6 else ICMP_ECHO
    header = struct.pack("!BBHHH", kind, 0, 0, ident, seq)
    if v6:
        return header + data
    return struct.pack("!BBHHH", kind, 0, checksum(header + data), ident, seq) + data


@dataclass(frozen=True, slots=True)
class Heard:
    """A packet that's about one of our echo requests."""

    status: ProbeStatus
    detail: str
    ident: int
    seq: int
    quoted_dest: str | None  # for an ICMP error: where the probe it quotes was going


def parse_packet(packet: bytes, v6: bool) -> Heard | None:
    """An echo reply, or an ICMP error quoting an echo request; None for anything else.

    IPv4 packets from macOS and from raw sockets start with the IP header; a Linux
    ping socket's don't. ICMPv6 never comes with its IP header.
    """
    if not v6 and packet and packet[0] >> 4 == 4:
        packet = packet[(packet[0] & 0x0F) * 4:]
    if len(packet) < 8:
        return None
    kind, code = packet[0], packet[1]
    if kind == (ICMP6_ECHO_REPLY if v6 else ICMP_ECHO_REPLY):
        ident, seq = struct.unpack("!HH", packet[4:8])
        return Heard(ProbeStatus.REPLY, "", ident, seq, None)
    status, detail = error_status(kind, code, v6)
    if status is None:
        return None
    quoted = packet[8:]  # the start of the packet the error is about
    if v6:
        if len(quoted) < 48 or quoted[6] != socket.IPPROTO_ICMPV6:
            return None
        dest, probe = socket.inet_ntop(socket.AF_INET6, quoted[24:40]), quoted[40:48]
    else:
        if len(quoted) < 20 or quoted[0] >> 4 != 4 or quoted[9] != socket.IPPROTO_ICMP:
            return None
        length = (quoted[0] & 0x0F) * 4
        dest, probe = socket.inet_ntoa(quoted[16:20]), quoted[length:length + 8]
    if len(probe) < 8 or probe[0] != (ICMP6_ECHO if v6 else ICMP_ECHO):
        return None
    ident, seq = struct.unpack("!HH", probe[4:8])
    return Heard(status, detail, ident, seq, dest)


def parse_error_queue(data: bytes, ancdata: list[tuple[int, int, bytes]], v6: bool
                      ) -> tuple[ProbeStatus, str, str | None, int | None] | None:
    """An entry from a Linux socket's error queue: (status, detail, who sent it, the probe's seq).

    `data` is what the error quoted of our probe, starting at its ICMP header.
    """
    for level, kind, cmsg in ancdata:
        if (level, kind) not in ((socket.IPPROTO_IP, IP_RECVERR),
                                 (socket.IPPROTO_IPV6, IPV6_RECVERR)):
            continue
        if len(cmsg) < _EXTENDED_ERR.size:
            return None
        errno, origin, icmp_type, icmp_code, _, _, _ = _EXTENDED_ERR.unpack_from(cmsg)
        seq = struct.unpack("!H", data[6:8])[0] if len(data) >= 8 else None
        if origin not in (SO_EE_ORIGIN_ICMP, SO_EE_ORIGIN_ICMP6):
            return ProbeStatus.ERROR, os.strerror(errno), None, seq
        status, detail = error_status(icmp_type, icmp_code, origin == SO_EE_ORIGIN_ICMP6)
        if status is None:
            return None
        sender = cmsg[_EXTENDED_ERR.size:]  # a sockaddr_in or sockaddr_in6
        if origin == SO_EE_ORIGIN_ICMP6 and len(sender) >= 24:
            responder = socket.inet_ntop(socket.AF_INET6, sender[8:24])
        elif origin == SO_EE_ORIGIN_ICMP and len(sender) >= 8:
            responder = socket.inet_ntoa(sender[4:8])
        else:
            responder = None
        return status, detail, responder, seq
    return None


class PosixIcmpProber(Prober):
    """ICMP echo (IPv4 and IPv6) with per-probe TTL, through ping sockets or raw sockets."""

    name = "icmp"
    supports_ttl = True

    def __init__(self) -> None:
        self.raw = _need_raw()
        # A Linux ping socket only hears replies to itself, and errors come on its error queue.
        self._error_queue = sys.platform == "linux" and not self.raw
        self._ident = random.randrange(1 << 16)
        self._seq = random.randrange(1 << 16)

    async def probe(self, dest: str, *, ttl: int = 64, timeout: float = 1.0,
                    size: int = 32) -> ProbeResult:
        sent_at = time.time()
        v6 = ":" in dest
        target = ipaddress.ip_address(dest)
        self._seq = (self._seq + 1) & 0xFFFF
        seq = self._seq
        try:
            sock = self._socket(v6, ttl)
        except OSError as e:
            return ProbeResult(dest, ttl, ProbeStatus.ERROR, None, None, sent_at, e.strerror or str(e))
        loop = asyncio.get_running_loop()
        heard: asyncio.Future[tuple[ProbeStatus, str, str | None, int]] = loop.create_future()

        def readable() -> None:
            for _ in range(64):  # a raw socket hears everyone's ICMP: don't spin on a flood
                try:
                    answer = self._read(sock, v6, target, seq)
                except BlockingIOError:
                    return
                except OSError:
                    continue  # a Linux socket reports a queued error once more, on plain recv
                if answer is not None and not heard.done():
                    heard.set_result((*answer, time.perf_counter_ns()))
                    return

        with sock:
            start = time.perf_counter_ns()
            try:
                sock.sendto(echo_request(self._ident, seq, payload(size), v6), (dest, 0))
            except OSError as e:
                return ProbeResult(dest, ttl, ProbeStatus.ERROR, None, None, sent_at,
                                   e.strerror or str(e))
            loop.add_reader(sock.fileno(), readable)
            try:
                async with asyncio.timeout(timeout):
                    status, detail, responder, end = await heard
            except TimeoutError:
                return ProbeResult(dest, ttl, ProbeStatus.TIMEOUT, None, None, sent_at)
            finally:
                loop.remove_reader(sock.fileno())
        if not status.answered:
            return ProbeResult(dest, ttl, status, None, None, sent_at, detail)
        return ProbeResult(dest, ttl, status, responder, (end - start) / 1e6, sent_at, detail)

    def _socket(self, v6: bool, ttl: int) -> socket.socket:
        family, level = (socket.AF_INET6, socket.IPPROTO_IPV6) if v6 else (socket.AF_INET, socket.IPPROTO_IP)
        proto = socket.IPPROTO_ICMPV6 if v6 else socket.IPPROTO_ICMP
        sock = socket.socket(family, socket.SOCK_RAW if self.raw else socket.SOCK_DGRAM, proto)
        try:
            sock.setblocking(False)
            sock.setsockopt(level, socket.IPV6_UNICAST_HOPS if v6 else socket.IP_TTL, ttl)
            if self._error_queue:
                sock.setsockopt(level, IPV6_RECVERR if v6 else IP_RECVERR, 1)
        except BaseException:
            sock.close()
            raise
        return sock

    def _read(self, sock: socket.socket, v6: bool,
              target: ipaddress.IPv4Address | ipaddress.IPv6Address, seq: int
              ) -> tuple[ProbeStatus, str, str | None] | None:
        """One packet off the socket, if it's the answer to our probe. Raises BlockingIOError
        when there's nothing left to read."""
        if self._error_queue:
            try:
                data, ancdata, _, _ = sock.recvmsg(512, socket.CMSG_SPACE(512), MSG_ERRQUEUE)
            except BlockingIOError:
                pass
            else:
                entry = parse_error_queue(data, ancdata, v6)
                if entry is None or entry[3] not in (seq, None):
                    return None
                return entry[0], entry[1], entry[2]
        packet, address = sock.recvfrom(65535)
        heard = parse_packet(packet, v6)
        if heard is None or heard.seq != seq:
            return None
        sender = ipaddress.ip_address(address[0].split("%")[0])
        if heard.status is ProbeStatus.REPLY:
            # A ping socket's replies are its own (Linux rewrites the identifier); elsewhere
            # everyone's ICMP arrives, so the identifier and the sender must match too.
            if not self._error_queue and (heard.ident != self._ident or sender != target):
                return None
        elif heard.ident != self._ident or ipaddress.ip_address(heard.quoted_dest) != target:
            return None
        return heard.status, heard.detail, str(sender)


def _need_raw() -> bool:
    """Whether this process must use raw sockets: False if ping sockets work, True if only raw
    ones do. Raises PermissionError, saying what to change, if neither does."""
    for kind in (socket.SOCK_DGRAM, socket.SOCK_RAW):
        try:
            socket.socket(socket.AF_INET, kind, socket.IPPROTO_ICMP).close()
        except PermissionError:
            continue
        return kind == socket.SOCK_RAW
    raise PermissionError(no_ping_sockets())
