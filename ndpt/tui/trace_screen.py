"""The trace screen: an mtr-style hop table with a sparkline per hop, and notes on reading it."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Footer, Header, Static

from ndpt.core.backends import Prober
from ndpt.core.models import Hop
from ndpt.core.resolve import Resolver
from ndpt.core.trace import TraceSession
from ndpt.textviz import fmt_ms, hop_label, host_label, last_cell, loss_cell
from ndpt.tui.widgets import (MAX_HISTORY, HistoryScreen, HostPrompt, SessionScreen, cell, heading,
                              share_width, spark)

if TYPE_CHECKING:
    from ndpt.tui.app import Settings

# Columns after "#" and "Host": (heading, width).
NUMBERS = (("Loss", 6), ("Sent", 5), ("Last", 7), ("Avg", 5), ("Best", 5), ("Worst", 5),
           ("StDev", 5))
TTL_WIDTH = 3
EVENTS_SHOWN = 3


class TraceScreen(SessionScreen):
    """Traces the route to one host, round after round. A new host starts a new trace."""

    TITLE = "NDPT trace"
    BINDINGS = [
        Binding("a", "choose_host", "Trace host"),
        Binding("enter", "history", "Hop history", priority=True),  # before DataTable's own Enter
    ]

    def __init__(self, prober: Prober, resolver: Resolver, settings: Settings) -> None:
        super().__init__()
        self.prober = prober
        self.resolver = resolver
        self.settings = settings
        self.target: str | None = None      # what to trace, even before the screen is up
        self.session: TraceSession | None = None
        self._ready = False                 # the table has its columns

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="hop-table", cursor_type="row", zebra_stripes=True)
        yield Static(id="trace-notes")
        yield Footer()

    def on_mount(self) -> None:
        super().on_mount()
        table = self.query_one(DataTable)
        table.border_title = "hops, ms"
        table.add_column(heading("#"), width=TTL_WIDTH, key="ttl")
        table.add_column("Host", key="host")
        for name, width in NUMBERS:
            table.add_column(heading(name), width=width, key=name)
        table.add_column("History", key="history")
        self._ready = True
        if self.target is not None:
            self.trace(self.target)
        self.refresh_view()

    def trace(self, host: str) -> None:
        """Trace `host` from scratch, stopping any trace already running."""
        if self.session is not None:
            self.session.stop()
            self.session = None
        self.target = host
        if not self._ready:
            return  # on_mount starts it
        s = self.settings
        session = TraceSession(host, self.prober, resolver=self.resolver, family=s.family,
                               max_hops=s.max_hops, interval=s.interval, timeout=s.timeout,
                               size=s.size, lookup_names=s.lookup_names)
        session.event_listeners.append(lambda text: self._on_event(session, text))
        self.session = session
        self.query_one(DataTable).clear()
        self.run_session(session)
        self.refresh_view()

    def _on_event(self, session: TraceSession, text: str) -> None:
        """Route changes pop up as they happen; what round 1 finds is shown below the table."""
        if session is self.session and session.round > 1:
            self.notify(text, title="route change", timeout=8)

    def refresh_view(self) -> None:
        session = self.session
        notes = self.query_one("#trace-notes", Static)
        if session is None:
            self.sub_title = "press a to choose a host to trace"
            notes.update("")
            return
        target = session.host
        if session.address and session.address != session.host:
            target += f" ({session.address})"
        paused = "  [paused]" if session.paused else ""
        self.sub_title = f"to {target}, round {session.round}, every {session.interval:g}s{paused}"
        self._fill_table(session)
        lines = [Text(session.error, style="red")] if session.error else []
        lines += [Text(f"note: {note}", style="yellow") for note in session.notes()]
        lines += [Text(f"- {event}", style="dim") for event in session.events[-EVENTS_SHOWN:]]
        notes.update(Text("\n").join(lines))

    def _fill_table(self, session: TraceSession) -> None:
        table = self.query_one(DataTable)
        hops = session.visible_hops
        keys = {str(hop.ttl) for hop in hops}
        for row_key in list(table.rows):
            if row_key.value not in keys:
                table.remove_row(row_key)
        labels = [hop_label(hop, session) for hop in hops]
        fixed = TTL_WIDTH + sum(width for _, width in NUMBERS)
        longest = max((Text(label).cell_len if isinstance(label, str) else label.cell_len
                       for label in labels), default=10)
        host_width, history = share_width(table.scrollable_content_region.width, fixed,
                                          len(NUMBERS) + 3, longest, MAX_HISTORY)
        columns = ["ttl", "host", *(name for name, _ in NUMBERS), "history"]
        for hop, label in zip(hops, labels):
            s = hop.stats
            style = "bold" if hop.ttl == session.dest_ttl else ""
            numbers = [loss_cell(s.sent, s.loss_pct), str(s.sent), last_cell(hop.last_status, s.last),
                       fmt_ms(s.avg), fmt_ms(s.best), fmt_ms(s.worst), fmt_ms(s.stdev)]
            cells = [cell(Text(str(hop.ttl), style=style), justify="right"),
                     cell(Text(label, style=style) if isinstance(label, str) else label, host_width),
                     *(cell(n, justify="right") for n in numbers),
                     cell(spark(s.recent()[-history:]) if history else Text(), justify="right")]
            key = str(hop.ttl)
            if key in table.rows:
                for column, value in zip(columns, cells):
                    table.update_cell(key, column, value, update_width=column in ("host", "history"))
            else:
                table.add_row(*cells, key=key)

    def highlighted(self) -> Hop | None:
        if self.session is None:
            return None
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return next((h for h in self.session.visible_hops if str(h.ttl) == row_key.value), None)

    def action_choose_host(self) -> None:
        self.app.push_screen(HostPrompt("Trace the route to which host?", self.target or ""),
                             self._chosen)

    def _chosen(self, host: str | None) -> None:
        if host:
            self.trace(host)

    def action_history(self) -> None:
        hop, session = self.highlighted(), self.session
        if hop is None or session is None:
            return

        def title() -> Text:
            label = hop_label(hop, session)
            return Text(f"hop {hop.ttl}: ").append_text(label if isinstance(label, Text) else Text(label))

        def details() -> list[Text | str]:
            names = [(host_label(session.resolver.cached(a) if session.lookup_names else None, a), n)
                     for a, n in hop.responders.most_common()]
            lines: list[Text | str] = []
            if names:
                lines.append("answered by " + ", ".join(f"{name} x{n}" for name, n in names))
            lines += [Text(f"note: {note}", style="yellow") for note in session.notes()
                      if note.startswith(f"hop {hop.ttl}:")]
            return lines

        self.app.push_screen(HistoryScreen(title, hop.stats, details))
