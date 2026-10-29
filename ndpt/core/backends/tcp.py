"""TCP "ping": time the handshake to a port."""

from __future__ import annotations

import asyncio
import contextlib
import time

from ndpt.core.backends.base import Prober
from ndpt.core.models import ProbeResult, ProbeStatus


class TcpProber(Prober):
    """Times TCP connects to `port`. Gets through where ICMP is filtered, but can't trace.

    Point it at an open port (443, 80, 22). A closed port still proves the host
    is up, but Windows retries the connect after the reset, so the time it
    reports for a closed port is inflated.
    """

    name = "tcp"
    supports_ttl = False

    def __init__(self, port: int = 443) -> None:
        self.port = port

    async def probe(self, dest: str, *, ttl: int = 64, timeout: float = 1.0,
                    size: int = 32) -> ProbeResult:
        sent_at = time.time()
        start = time.perf_counter_ns()
        try:
            async with asyncio.timeout(timeout):
                _, writer = await asyncio.open_connection(dest, self.port)
        except TimeoutError:
            return ProbeResult(dest, ttl, ProbeStatus.TIMEOUT, None, None, sent_at)
        except ConnectionRefusedError:
            rtt = (time.perf_counter_ns() - start) / 1e6
            return ProbeResult(dest, ttl, ProbeStatus.REPLY, dest, rtt, sent_at,
                               f"port {self.port} closed")
        except OSError as e:
            return ProbeResult(dest, ttl, ProbeStatus.ERROR, None, None, sent_at, e.strerror or str(e))
        rtt = (time.perf_counter_ns() - start) / 1e6
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
        return ProbeResult(dest, ttl, ProbeStatus.REPLY, dest, rtt, sent_at)
