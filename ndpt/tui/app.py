"""The Textual app: a ping screen and a trace screen over one prober, on Textual's own loop."""

from __future__ import annotations

import socket
from collections.abc import Sequence
from dataclasses import dataclass

from textual.app import App
from textual.binding import Binding

from ndpt.core.backends import Prober
from ndpt.core.resolve import Resolver
from ndpt.tui.ping_screen import PingScreen
from ndpt.tui.trace_screen import TraceScreen


@dataclass(frozen=True)
class Settings:
    """How both screens probe."""

    interval: float = 1.0
    timeout: float = 1.0
    size: int = 32
    family: int = socket.AF_UNSPEC
    max_hops: int = 30
    lookup_names: bool = True


class NdptApp(App):
    """Two screens, each with its own session, sharing the prober and the name cache.

    Each screen is a mode, so a hop history left open on the trace screen is
    still there after a visit to the ping screen. Sessions run in workers on
    Textual's loop; screens read their state on a timer. A session keeps
    running while its screen is hidden; space pauses the one on show.
    """

    TITLE = "NDPT"
    ENABLE_COMMAND_PALETTE = False
    MODES = {"ping": "ping", "trace": "trace"}  # installed screens, by name
    BINDINGS = [
        Binding("p", "show_ping", "Ping"),
        Binding("t", "show_trace", "Trace"),
        Binding("q", "quit", "Quit"),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]
    CSS = """
    PingStrip {
        height: auto;
        max-height: 50%;
        border: round $primary;
        padding: 0 1;
    }
    DataTable {
        height: 1fr;
        border: round $primary;
    }
    #trace-notes {
        height: auto;
        max-height: 8;
        padding: 0 1;
    }
    HostPrompt, HistoryScreen {
        align: center middle;
    }
    .dialog {
        width: 70;
        height: auto;
        border: round $accent;
        background: $surface;
        padding: 0 1;
    }
    .dialog.history {
        width: 90%;
    }
    HistoryChart {
        height: 14;
        margin: 1 0 0 0;
    }
    .hint {
        color: $text-muted;
    }
    """

    def __init__(self, prober: Prober, resolver: Resolver, settings: Settings = Settings(), *,
                 hosts: Sequence[str] = (), start: str = "ping") -> None:
        super().__init__()
        self.prober = prober
        self.resolver = resolver
        self.settings = settings
        self.hosts = list(hosts)
        self.start = start

    def on_mount(self) -> None:
        self.ping_screen = PingScreen(self.hosts, self.prober, self.resolver, self.settings)
        self.trace_screen = TraceScreen(self.prober, self.resolver, self.settings)
        self.install_screen(self.ping_screen, "ping")
        self.install_screen(self.trace_screen, "trace")
        if self.start == "trace" and self.hosts:
            self.trace_screen.target = self.hosts[0]
        self.switch_mode(self.start)

    def action_show_ping(self) -> None:
        self.switch_mode("ping")

    async def action_show_trace(self) -> None:
        await self.switch_mode("trace")
        if self.trace_screen.target is None:
            target = self.ping_screen.highlighted()
            if target is not None:
                self.trace_screen.trace(target.name)
            else:
                self.trace_screen.action_choose_host()

    async def trace(self, host: str) -> None:
        """Show the trace screen, tracing `host` (from scratch, unless it's already the one)."""
        await self.switch_mode("trace")
        if host != self.trace_screen.target or self.trace_screen.session is None:
            self.trace_screen.trace(host)

    async def action_quit(self) -> None:
        for screen in (self.ping_screen, self.trace_screen):
            if screen.session is not None:
                screen.session.stop()  # probes in flight are dropped, not waited for
        self.exit()
