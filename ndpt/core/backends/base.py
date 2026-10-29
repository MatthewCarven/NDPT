"""What every prober provides."""

from __future__ import annotations

import abc

from ndpt.core.models import ProbeResult


class Prober(abc.ABC):
    """Sends one probe at a time to an address and reports what came back.

    Probes may be in flight concurrently; sessions rely on that to trace every
    hop of a route at once.
    """

    name: str = "?"
    supports_ttl: bool = True  # can it set the TTL and hear "time exceeded"? Tracing needs it.

    @abc.abstractmethod
    async def probe(self, dest: str, *, ttl: int = 64, timeout: float = 1.0,
                    size: int = 32) -> ProbeResult:
        """Probe the address `dest` and wait for an answer, or for `timeout` seconds."""

    async def aclose(self) -> None:
        """Release whatever the prober holds."""

    async def __aenter__(self) -> Prober:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
