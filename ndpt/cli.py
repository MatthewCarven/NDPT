"""Command line: `python -m ndpt ping|trace ...` with live tables."""

from __future__ import annotations

import argparse
import asyncio
import socket
import sys
from collections.abc import Callable, Sequence

from rich import box
from rich.console import Console, Group, RenderableType
from rich.live import Live
from rich.table import Table
from rich.text import Text

from ndpt import __version__
from ndpt.core.backends import Prober, make_prober
from ndpt.core.backends.fake import DemoResolver, FakeProber, demo_route
from ndpt.core.models import ProbeStatus
from ndpt.core.ping import PingSession
from ndpt.core.resolve import Resolver
from ndpt.core.session import MAX_PAYLOAD, Session
from ndpt.core.trace import TraceSession
from ndpt.textviz import fmt_ms, loss_style, sparkline

HISTORY = 30          # samples in each row's sparkline
MIN_INTERVAL = 0.1    # for real probes, so a typo can't flood the network

_SHORT_STATUS = {ProbeStatus.TIMEOUT: "timeout", ProbeStatus.UNREACHABLE: "unreach",
                 ProbeStatus.ERROR: "error"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ndpt", description="Network diagnostics: ping and traceroute.")
    parser.add_argument("--version", action="version", version=f"ndpt {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-i", "--interval", type=float, default=1.0,
                        help="seconds between probes (default 1)")
    common.add_argument("-W", "--timeout", type=float, default=1.0,
                        help="seconds to wait for each answer (default 1)")
    common.add_argument("-s", "--size", type=int, default=32,
                        help="payload bytes (default 32, as Windows ping)")
    family = common.add_mutually_exclusive_group()
    family.add_argument("-4", dest="family", action="store_const", const=socket.AF_INET,
                        default=socket.AF_UNSPEC, help="IPv4 only")
    family.add_argument("-6", dest="family", action="store_const", const=socket.AF_INET6,
                        default=socket.AF_UNSPEC, help="IPv6 only")
    common.add_argument("--report", action="store_true",
                        help="no live display; print the table once at the end")
    common.add_argument("--demo", action="store_true",
                        help="a made-up network: no packets are sent")

    ping = sub.add_parser("ping", parents=[common], help="ping one or more hosts side by side")
    ping.add_argument("hosts", nargs="+")
    ping.add_argument("-c", "--count", type=int, help="stop after this many probes per host")
    ping.add_argument("--tcp", type=int, metavar="PORT",
                      help="time TCP handshakes to an open PORT instead (for hosts that filter ping)")

    trace = sub.add_parser("trace", parents=[common], help="trace the route to a host, mtr-style")
    trace.add_argument("host")
    trace.add_argument("-c", "--count", type=int, help="stop after this many rounds")
    trace.add_argument("-m", "--max-hops", type=int, default=30, help="default 30")
    trace.add_argument("-n", "--numeric", action="store_true", help="don't look up hop names")

    sub.add_parser("tui", help="terminal UI (not built yet)")
    sub.add_parser("gui", help="desktop UI (not built yet)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command in ("tui", "gui"):
        phase = 2 if args.command == "tui" else 3
        print(f"The {args.command.upper()} isn't built yet: it's phase {phase} of PLAN.md.",
              file=sys.stderr)
        return 2
    problem = _check(args)
    if problem:
        parser.error(problem)

    console = Console(highlight=False)
    ascii_only = not console.encoding.lower().startswith("utf")
    port = getattr(args, "tcp", None)
    if args.demo:
        prober: Prober = FakeProber(route_factory=demo_route, time_scale=1.0)
        resolver: Resolver = DemoResolver()
    else:
        resolver = Resolver()
        try:
            prober = make_prober("tcp" if port else "icmp", port=port or 443)
        except (NotImplementedError, OSError) as e:
            console.print(f"[red]{e}")
            return 1

    session: Session
    render: Callable[[], RenderableType]
    if args.command == "ping":
        session = PingSession(args.hosts, prober, resolver=resolver, family=args.family,
                              interval=args.interval, timeout=args.timeout, size=args.size,
                              count=args.count)
        render = lambda: ping_table(session, ascii_only, console.width)  # noqa: E731
    else:
        session = TraceSession(args.host, prober, resolver=resolver, family=args.family,
                               max_hops=args.max_hops, interval=args.interval,
                               timeout=args.timeout, size=args.size, rounds=args.count,
                               lookup_names=not args.numeric)
        render = lambda: trace_view(session, ascii_only, console.width)  # noqa: E731

    try:
        asyncio.run(_run(session, prober, render, console, live=console.is_terminal and not args.report))
    except KeyboardInterrupt:
        pass
    console.print(render())
    return _exit_code(session)


def _check(args: argparse.Namespace) -> str | None:
    if args.interval <= 0 or args.timeout <= 0:
        return "interval and timeout must be positive"
    if not args.demo and args.interval < MIN_INTERVAL:
        return f"interval below {MIN_INTERVAL}s is only allowed with --demo"
    if not 0 <= args.size <= MAX_PAYLOAD:
        return f"size must be between 0 and {MAX_PAYLOAD}"
    if args.count is not None and args.count < 1:
        return "count must be at least 1"
    if getattr(args, "tcp", None) is not None and not 1 <= args.tcp <= 65535:
        return "TCP port must be between 1 and 65535"
    max_hops = getattr(args, "max_hops", None)
    if max_hops is not None and not 1 <= max_hops <= 255:
        return "max hops must be between 1 and 255"
    return None


async def _run(session: Session, prober: Prober, render: Callable[[], RenderableType],
               console: Console, live: bool) -> None:
    task = asyncio.create_task(session.run())
    try:
        if live:
            hint = Text("Ctrl+C to stop", style="dim")
            with Live(render(), console=console, auto_refresh=False, transient=True) as view:
                while not task.done():
                    await asyncio.wait({task}, timeout=0.25)
                    view.update(Group(render(), hint), refresh=True)
        await task
    finally:
        session.stop()
        if not task.done():
            await asyncio.wait({task}, timeout=2.0)
            task.cancel()
        await prober.aclose()


def _exit_code(session: Session) -> int:
    if isinstance(session, PingSession):
        return 0 if all(t.stats.received for t in session.targets) else 1
    return 1 if session.error else 0


_NUMBER_WIDTHS = {"Sent": 4, "Loss": 6, "Last": 7, "Jitter": 6}  # "100.0%", "timeout"


def _layout(width: int, numbers: Sequence[str], lead: int = 0) -> tuple[int, int]:
    """Widths for the host column and the sparkline, from what the number columns leave.

    The number columns never shrink, and rich crops a no-wrap table rather than
    squeezing it, so the host width is worked out here. A narrow terminal
    loses the sparkline (0) before host names get unreadable. Rich puts 3
    characters between columns and 1 at each edge; `lead` is any column
    before the host column (the trace's hop number).
    """
    columns = len(numbers) + 2 + (1 if lead else 0)  # + host + sparkline
    fixed = lead + sum(_NUMBER_WIDTHS.get(n, 5) for n in numbers) + 3 * (columns - 1) + 2
    spare = width - fixed
    if spare < 24 + 8:
        return max(10, spare + 3), 0  # no sparkline: its separator goes back to the host
    history = max(8, min(HISTORY, spare - 44))
    return min(44, spare - history), history


def _number_columns(table: Table, names: Sequence[str]) -> None:
    for name in names:
        table.add_column(name, justify="right", no_wrap=True, min_width=_NUMBER_WIDTHS.get(name, 5))


def _host_label(name: str | None, address: str) -> str:
    return f"{name} ({address})" if name and name != address else address


def ping_table(session: PingSession, ascii_only: bool = False, width: int = 120) -> Table:
    numbers = ("Sent", "Loss", "Last", "Avg", "Best", "Worst", "Jitter")
    host, history = _layout(width, numbers)
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, title_justify="left",
                  title=f"ping ({session.prober.name}) every {session.interval:g}s, times in ms")
    table.add_column("Host", no_wrap=True, overflow="ellipsis", max_width=host)
    _number_columns(table, numbers)
    if history:
        table.add_column("History", no_wrap=True, min_width=history)
    for target in session.targets:
        if target.error:
            table.add_row(Text(f"{target.name}: {target.error}", style="red"))
            continue
        s = target.stats
        label = _host_label(target.name, target.address) if target.address else target.name
        cells = [label, str(s.sent), _loss(s.sent, s.loss_pct),
                 _last(target.last_status, s.last, echo_only=True), fmt_ms(s.avg),
                 fmt_ms(s.best), fmt_ms(s.worst), fmt_ms(s.jitter) if s.received > 1 else "-"]
        if history:
            cells.append(sparkline(s.recent()[-history:], ascii_only=ascii_only))
        table.add_row(*cells)
    return table


def trace_view(session: TraceSession, ascii_only: bool = False, width: int = 120) -> RenderableType:
    if session.error:
        return Text(session.error, style="red")
    target = session.host
    if session.address and session.address != session.host:
        target += f" ({session.address})"
    table = Table(box=box.SIMPLE_HEAD, pad_edge=False, title_justify="left",
                  title=f"trace to {target}, round {session.round}, times in ms")
    numbers = ("Loss", "Sent", "Last", "Avg", "Best", "Worst", "StDev")
    host, history = _layout(width, numbers, lead=2)
    table.add_column("#", justify="right", no_wrap=True, min_width=2)
    table.add_column("Host", no_wrap=True, overflow="ellipsis", max_width=host)
    _number_columns(table, numbers)
    if history:
        table.add_column("History", no_wrap=True, min_width=history)
    for hop in session.visible_hops:
        s = hop.stats
        cells = [str(hop.ttl), _hop_host(hop.address, len(hop.responders), session),
                 _loss(s.sent, s.loss_pct), str(s.sent), _last(hop.last_status, s.last),
                 fmt_ms(s.avg), fmt_ms(s.best), fmt_ms(s.worst), fmt_ms(s.stdev)]
        if history:
            cells.append(sparkline(s.recent()[-history:], ascii_only=ascii_only))
        table.add_row(*cells, style="bold" if hop.ttl == session.dest_ttl else None)
    parts: list[RenderableType] = [table]
    parts += [Text(f"note: {note}", style="yellow") for note in session.notes()]
    parts += [Text(f"- {event}", style="dim") for event in session.events[-3:]]
    return Group(*parts)


def _hop_host(address: str | None, responders: int, session: TraceSession) -> Text | str:
    if address is None:
        return Text("???", style="dim")
    name = session.resolver.cached(address) if session.lookup_names else None
    label = _host_label(name, address)
    if responders > 1:
        label += f" +{responders - 1}"
    return label


def _loss(sent: int, pct: float) -> Text | str:
    return Text(f"{pct:.1f}%", style=loss_style(pct)) if sent else "-"


def _last(status: ProbeStatus | None, last_rtt: float | None, echo_only: bool = False) -> Text | str:
    """The latest probe: its time if it was answered, else what happened to it.

    A ping only counts an echo reply; a trace hop counts any answer."""
    if status is None:
        return "-"
    if status is ProbeStatus.REPLY or (status.answered and not echo_only):
        return fmt_ms(last_rtt)
    return Text(_SHORT_STATUS.get(status, status.value), style="red")
