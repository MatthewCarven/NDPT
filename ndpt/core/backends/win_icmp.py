"""ICMP echo through Windows' own ICMP API (iphlpapi.dll).

This is the API ping.exe and tracert.exe use. It needs no Administrator rights
and no packet driver, and it lets each probe set its own TTL, which is all a
traceroute needs. The calls block, so they run on a thread pool; ctypes
releases the GIL while they wait.
"""

from __future__ import annotations

import asyncio
import ctypes
import socket
import struct
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from ctypes import wintypes

from ndpt.core.backends.base import Prober
from ndpt.core.models import ProbeResult, ProbeStatus

# Status codes from ipexport.h. The IPv6 names share the IPv4 numbers.
IP_SUCCESS = 0
IP_STATUS_BASE = 11000
IP_REQ_TIMED_OUT = 11010
IP_TTL_EXPIRED_TRANSIT = 11013  # IPv6: IP_HOP_LIMIT_EXCEEDED
IP_TIME_EXCEEDED = 11041        # IPv6 only

_UNREACHABLE = {
    11002: "network unreachable",          # IPv6: no route
    11003: "host unreachable",             # IPv6: address unreachable
    11004: "protocol unreachable",         # IPv6: administratively prohibited
    11005: "port unreachable",
    11040: "destination unreachable",      # IPv6 only
}
_ERRORS = {
    11001: "reply buffer too small",
    11006: "no resources",
    11007: "bad option",
    11008: "hardware error",
    11009: "packet too big",
    11011: "bad request",
    11012: "bad route",
    11014: "fragment reassembly timed out",
    11015: "parameter problem",
    11016: "source quench",
    11017: "option too big",
    11018: "bad destination",
    11050: "general failure",
}

_PAYLOAD = b"abcdefghijklmnopqrstuvw"  # what Windows ping sends


def classify(code: int) -> tuple[ProbeStatus, str]:
    """Map an IcmpSendEcho status (or a Windows error code) to a ProbeStatus and a reason."""
    if code == IP_SUCCESS:
        return ProbeStatus.REPLY, ""
    if code in (IP_TTL_EXPIRED_TRANSIT, IP_TIME_EXCEEDED):
        return ProbeStatus.TTL_EXPIRED, ""
    if code == IP_REQ_TIMED_OUT:
        return ProbeStatus.TIMEOUT, ""
    if code in _UNREACHABLE:
        return ProbeStatus.UNREACHABLE, _UNREACHABLE[code]
    if code in _ERRORS:
        return ProbeStatus.ERROR, _ERRORS[code]
    if code < IP_STATUS_BASE and sys.platform == "win32":
        return ProbeStatus.ERROR, ctypes.FormatError(code).strip()
    return ProbeStatus.ERROR, f"status {code}"


def combine_rtt(api_ms: int, wall_ms: float) -> float:
    """The best round-trip time we can get from one probe.

    The API rounds the round trip down to whole milliseconds, so a LAN hop reads
    0. Our own clock around the call is finer, but it also counts thread
    scheduling. So trust our clock only inside the millisecond the API reported.
    """
    return min(max(wall_ms, float(api_ms)), api_ms + 1.0)


class IP_OPTION_INFORMATION(ctypes.Structure):
    _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte), ("Flags", ctypes.c_ubyte),
                ("OptionsSize", ctypes.c_ubyte), ("OptionsData", ctypes.c_void_p)]


class ICMP_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", ctypes.c_uint32), ("Status", ctypes.c_ulong),
                ("RoundTripTime", ctypes.c_ulong), ("DataSize", ctypes.c_ushort),
                ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p),
                ("Options", IP_OPTION_INFORMATION)]


class IPV6_ADDRESS_EX(ctypes.Structure):
    _pack_ = 1  # ipexport.h wraps this one in pshpack1.h
    _layout_ = "ms"
    _fields_ = [("sin6_port", ctypes.c_ushort), ("sin6_flowinfo", ctypes.c_ulong),
                ("sin6_addr", ctypes.c_ubyte * 16), ("sin6_scope_id", ctypes.c_ulong)]


class ICMPV6_ECHO_REPLY(ctypes.Structure):
    _fields_ = [("Address", IPV6_ADDRESS_EX), ("Status", ctypes.c_ulong),
                ("RoundTripTime", ctypes.c_uint)]


class SOCKADDR_IN6(ctypes.Structure):
    _fields_ = [("sin6_family", ctypes.c_short), ("sin6_port", ctypes.c_ushort),
                ("sin6_flowinfo", ctypes.c_ulong), ("sin6_addr", ctypes.c_ubyte * 16),
                ("sin6_scope_id", ctypes.c_ulong)]


_INVALID_HANDLE = ctypes.c_void_p(-1).value
_api = None


def _load():
    global _api
    if _api is None:
        if sys.platform != "win32":
            raise OSError("the Windows ICMP API needs Windows")
        dll = ctypes.WinDLL("iphlpapi", use_last_error=True)
        dll.IcmpCreateFile.restype = wintypes.HANDLE
        dll.Icmp6CreateFile.restype = wintypes.HANDLE
        dll.IcmpCloseHandle.argtypes = [wintypes.HANDLE]
        dll.IcmpCloseHandle.restype = wintypes.BOOL
        dll.IcmpSendEcho.argtypes = [
            wintypes.HANDLE, ctypes.c_uint32, ctypes.c_void_p, wintypes.WORD,
            ctypes.POINTER(IP_OPTION_INFORMATION), ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD]
        dll.IcmpSendEcho.restype = wintypes.DWORD
        dll.Icmp6SendEcho2.argtypes = [
            wintypes.HANDLE, wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p,
            ctypes.POINTER(SOCKADDR_IN6), ctypes.POINTER(SOCKADDR_IN6), ctypes.c_void_p,
            wintypes.WORD, ctypes.POINTER(IP_OPTION_INFORMATION), ctypes.c_void_p,
            wintypes.DWORD, wintypes.DWORD]
        dll.Icmp6SendEcho2.restype = wintypes.DWORD
        _api = dll
    return _api


def _open(create) -> int:
    handle = create()
    if handle is None or handle == _INVALID_HANDLE:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


def _payload(size: int) -> bytes:
    return (_PAYLOAD * (size // len(_PAYLOAD) + 1))[:size]


# Each echo returns (status code, responder, API round trip in ms, our own timing in ms).
# A handle per call keeps concurrent probes from sharing anything.

def _echo4(api, dest: str, ttl: int, timeout: float, size: int):
    address = struct.unpack("<I", socket.inet_aton(dest))[0]
    payload = _payload(size)
    reply = ctypes.create_string_buffer(ctypes.sizeof(ICMP_ECHO_REPLY) + size + 8 + 64)
    options = IP_OPTION_INFORMATION(Ttl=ttl)
    handle = _open(api.IcmpCreateFile)
    try:
        start = time.perf_counter_ns()
        count = api.IcmpSendEcho(handle, address, payload, size, ctypes.byref(options),
                                 reply, len(reply), int(timeout * 1000))
        wall = (time.perf_counter_ns() - start) / 1e6
        if count == 0:
            return ctypes.get_last_error(), None, None, wall
        echo = ICMP_ECHO_REPLY.from_buffer(reply)
        return echo.Status, socket.inet_ntoa(struct.pack("<I", echo.Address)), echo.RoundTripTime, wall
    finally:
        api.IcmpCloseHandle(handle)


def _echo6(api, dest: str, ttl: int, timeout: float, size: int):
    host, _, _, scope_id = socket.getaddrinfo(
        dest, None, socket.AF_INET6, flags=socket.AI_NUMERICHOST)[0][4]
    target = SOCKADDR_IN6(sin6_family=socket.AF_INET6, sin6_scope_id=scope_id)
    target.sin6_addr[:] = socket.inet_pton(socket.AF_INET6, host.split("%")[0])
    source = SOCKADDR_IN6(sin6_family=socket.AF_INET6)  # any local address
    payload = _payload(size)
    reply = ctypes.create_string_buffer(ctypes.sizeof(ICMPV6_ECHO_REPLY) + size + 8 + 64)
    options = IP_OPTION_INFORMATION(Ttl=ttl)
    handle = _open(api.Icmp6CreateFile)
    try:
        start = time.perf_counter_ns()
        count = api.Icmp6SendEcho2(handle, None, None, None, ctypes.byref(source),
                                   ctypes.byref(target), payload, size, ctypes.byref(options),
                                   reply, len(reply), int(timeout * 1000))
        wall = (time.perf_counter_ns() - start) / 1e6
        if count == 0:
            return ctypes.get_last_error(), None, None, wall
        echo = ICMPV6_ECHO_REPLY.from_buffer(reply)
        responder = socket.inet_ntop(socket.AF_INET6, bytes(echo.Address.sin6_addr))
        return echo.Status, responder, echo.RoundTripTime, wall
    finally:
        api.IcmpCloseHandle(handle)


class WinIcmpProber(Prober):
    """ICMP echo (IPv4 and IPv6) with per-probe TTL, via iphlpapi.dll."""

    name = "icmp"
    supports_ttl = True

    def __init__(self, max_concurrency: int = 64) -> None:
        self._api = _load()
        self._pool = ThreadPoolExecutor(max_workers=max_concurrency, thread_name_prefix="ndpt-icmp")

    async def probe(self, dest: str, *, ttl: int = 64, timeout: float = 1.0,
                    size: int = 32) -> ProbeResult:
        sent_at = time.time()
        echo = _echo6 if ":" in dest else _echo4
        loop = asyncio.get_running_loop()
        try:
            code, responder, api_rtt, wall = await loop.run_in_executor(
                self._pool, echo, self._api, dest, ttl, timeout, size)
        except OSError as e:
            return ProbeResult(dest, ttl, ProbeStatus.ERROR, None, None, sent_at, str(e))
        status, detail = classify(code)
        if not status.answered:
            return ProbeResult(dest, ttl, status, None, None, sent_at, detail)
        return ProbeResult(dest, ttl, status, responder, combine_rtt(api_rtt, wall), sent_at, detail)

    async def aclose(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)
