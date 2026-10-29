"""Forward and reverse DNS that never blocks the event loop."""

from __future__ import annotations

import asyncio
import ipaddress
import socket


class ResolveError(Exception):
    pass


class Resolver:
    """Turns names into addresses, and addresses back into names (cached).

    Reverse lookups can take seconds for addresses with no PTR record, so
    sessions start them in the background and front ends read `cached()`.
    """

    def __init__(self) -> None:
        self._names: dict[str, str | None] = {}
        self._pending: dict[str, asyncio.Task[str | None]] = {}

    async def resolve(self, host: str, family: int = socket.AF_UNSPEC) -> str:
        literal = _ip_literal(host, family)
        if literal is not None:
            return literal
        loop = asyncio.get_running_loop()
        try:
            infos = await loop.getaddrinfo(host, None, family=family, type=socket.SOCK_STREAM)
        except (socket.gaierror, UnicodeError) as e:
            raise ResolveError(f"can't resolve {host}: {getattr(e, 'strerror', None) or e}") from None
        if not infos:
            raise ResolveError(f"can't resolve {host}: no addresses")
        return infos[0][4][0]

    def cached(self, address: str) -> str | None:
        """The name for `address` if a reverse lookup has already finished, else None."""
        return self._names.get(address)

    async def reverse(self, address: str) -> str | None:
        if address in self._names:
            return self._names[address]
        task = self._pending.get(address)
        if task is None:
            task = self._pending[address] = asyncio.ensure_future(self._lookup(address))
        return await asyncio.shield(task)

    async def _lookup(self, address: str) -> str | None:
        loop = asyncio.get_running_loop()
        try:
            name, _ = await loop.getnameinfo((address, 0), socket.NI_NAMEREQD)
        except (OSError, UnicodeError):
            name = None
        self._names[address] = name
        self._pending.pop(address, None)
        return name


def _ip_literal(host: str, family: int) -> str | None:
    """`host` normalised if it's already an IP address, None if it's a name."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None
    wanted = {socket.AF_INET: 4, socket.AF_INET6: 6}.get(family)
    if wanted is not None and ip.version != wanted:
        raise ResolveError(f"{host} is not an IPv{wanted} address")
    return str(ip)
