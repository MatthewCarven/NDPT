"""Probers: the code that actually puts packets on the wire."""

from __future__ import annotations

import sys

from ndpt.core.backends.base import Prober


def make_prober(protocol: str = "icmp", *, port: int = 443) -> Prober:
    """The real prober for this platform: "icmp" (echo, can trace) or "tcp" (handshake to `port`)."""
    if protocol == "tcp":
        from ndpt.core.backends.tcp import TcpProber
        return TcpProber(port)
    if protocol == "icmp":
        if sys.platform == "win32":
            from ndpt.core.backends.win_icmp import WinIcmpProber
            return WinIcmpProber()
        from ndpt.core.backends.posix_icmp import PosixIcmpProber  # Linux, macOS
        return PosixIcmpProber()
    raise ValueError(f"unknown protocol {protocol!r}")


__all__ = ["Prober", "make_prober"]
