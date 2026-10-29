import ipaddress
import socket
import sys

import pytest

from ndpt.core.resolve import Resolver, ResolveError

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="needs the Windows ICMP API")


class StubResolver(Resolver):
    """Resolves IP literals and the names it's given, with no DNS traffic."""

    def __init__(self, names: dict[str, str] | None = None) -> None:
        super().__init__()
        self.names = names or {}

    async def resolve(self, host: str, family: int = socket.AF_UNSPEC) -> str:
        if host in self.names:
            return self.names[host]
        try:
            ipaddress.ip_address(host)
        except ValueError:
            raise ResolveError(f"can't resolve {host}: not in the stub") from None
        return await super().resolve(host, family)
