"""The ping screen: a latency line per host, and their numbers in a table below."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Header

from ndpt.core.backends import Prober
from ndpt.core.models import PingTarget
from ndpt.core.ping import PingSession
from ndpt.core.resolve import Resolver
from ndpt.textviz import fmt_ms, host_label, last_cell, loss_cell
from ndpt.tui.widgets import (HistoryScreen, HostPrompt, SessionScreen, cell, heading, share_width,
                              spark)

if TYPE_CHECKING:
    from ndpt.tui.app import Settings

# Number columns: (heading, width). Widths fit "100.0%", "timeout" and fmt_ms's 4 characters.
NUMBERS = (("Sent", 6), ("Loss", 6), ("Last", 7), ("Avg", 5), ("Best", 5), ("Worst", 5),
           ("StDev", 5), ("Jitter", 6), ("p95", 5))


def target_label(target: PingTarget) -> str:
    return host_label(target.name, target.address) if target.address else target.name


class PingStrip(Widget):
    """One line per host: its name, a sparkline as wide as the screen allows, last/avg/loss.

    The sparklines end at the same column, so "now" lines up for every host.
    """

    def __init__(self, session: PingSession) -> None:
        super().__init__()
        self.session = session

    def render(self) -> Text:
        width = self.content_size.width
        targets = self.session.targets
        if not targets:
            return Text("No hosts yet: press a to add one.", style="dim")
        labels = [target_label(t) for t in targets]
        name_width = min(max(len(label) for label in labels), max(12, width // 3))
        right_width = 32  # " last" (8) + "  avg " (6) + 5 + "  loss " (7) + 6
        history = max(0, width - name_width - 1 - right_width)
        lines = []
        for target, label in zip(targets, labels):
            line = cell(label, name_width)
            line.align("left", name_width)
            line.append(" ")
            if target.error:
                line.append(target.error, style="red")
            else:
                s = target.stats
                line.append_text(_fixed(spark(s.recent()[-history:]) if history else Text(), history))
                line.append_text(_fixed(last_cell(target.last_status, s.last, echo_only=True), 8))
                line.append("  avg ", style="dim")
                line.append_text(_fixed(fmt_ms(s.avg), 5))
                line.append("  loss ", style="dim")
                line.append_text(_fixed(loss_cell(s.sent, s.loss_pct), 6))
            line.no_wrap = True
            line.overflow = "crop"
            lines.append(line)
        return Text("\n", no_wrap=True).join(lines)


def _fixed(value: Text | str, width: int) -> Text:
    """Right-aligned in exactly `width` cells."""
    text = value.copy() if isinstance(value, Text) else Text(value)
    text.align("right", width)
    return text


class PingScreen(SessionScreen):
    """Pings every host on the app's list, side by side."""

    TITLE = "NDPT ping"
    BINDINGS = [
        Binding("a", "add_host", "Add host"),
        Binding("d,delete", "remove_host", "Remove"),
        Binding("h", "history", "History"),
        Binding("enter", "trace_host", "Trace host", priority=True),  # before DataTable's own Enter
    ]

    def __init__(self, hosts: Sequence[str], prober: Prober, resolver: Resolver,
                 settings: Settings) -> None:
        super().__init__()
        self._strip_lines = -1
        self.session = PingSession(hosts, prober, resolver=resolver, family=settings.family,
                                   interval=settings.interval, timeout=settings.timeout,
                                   size=settings.size, until_stopped=True)

    def compose(self) -> ComposeResult:
        yield Header()
        yield PingStrip(self.session)
        yield DataTable(id="ping-table", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        super().on_mount()
        self.query_one(PingStrip).border_title = "round-trip times, ms (newest on the right)"
        table = self.query_one(DataTable)
        table.border_title = "statistics, ms"
        table.add_column("Host", key="host")
        for name, width in NUMBERS:
            table.add_column(heading(name), width=width, key=name)
        self.run_session(self.session)
        self.refresh_view()

    def refresh_view(self) -> None:
        session = self.session
        description = f"{session.prober.name} every {session.interval:g}s"
        self.sub_title = description + ("  [paused]" if session.paused else "")
        lines = max(1, len(session.targets))
        self.query_one(PingStrip).refresh(layout=lines != self._strip_lines)  # its height is one line a host
        self._strip_lines = lines
        table = self.query_one(DataTable)
        keys = {self._key(t): t for t in session.targets}
        for row_key in list(table.rows):
            if row_key.value not in keys:
                table.remove_row(row_key)
        fixed = sum(width for _, width in NUMBERS)
        labels = [target_label(t) for t in session.targets]
        host_width, _ = share_width(table.scrollable_content_region.width, fixed, len(NUMBERS) + 1,
                                    max((len(label) for label in labels), default=10))
        for (key, target), label in zip(keys.items(), labels):
            cells = self._cells(target, label, host_width)
            if key in table.rows:
                for column, value in zip(["host", *(name for name, _ in NUMBERS)], cells):
                    table.update_cell(key, column, value, update_width=column == "host")
            else:
                table.add_row(*cells, key=key)

    @staticmethod
    def _key(target: PingTarget) -> str:
        return str(id(target))

    @staticmethod
    def _cells(target: PingTarget, label: str, host_width: int) -> list[Text]:
        if target.error:
            return [cell(Text(f"{label}: {target.error}", style="red"), host_width)] + \
                   [cell("-", justify="right") for _ in NUMBERS]
        s = target.stats
        numbers = [str(s.sent), loss_cell(s.sent, s.loss_pct),
                   last_cell(target.last_status, s.last, echo_only=True), fmt_ms(s.avg),
                   fmt_ms(s.best), fmt_ms(s.worst), fmt_ms(s.stdev),
                   fmt_ms(s.jitter) if s.received > 1 else "-", fmt_ms(s.percentile(95))]
        return [cell(label, host_width)] + [cell(n, justify="right") for n in numbers]

    def highlighted(self) -> PingTarget | None:
        """The host under the table's cursor, or the first host if the screen isn't up yet."""
        if not self.is_mounted:
            return self.session.targets[0] if self.session.targets else None
        table = self.query_one(DataTable)
        if not table.row_count:
            return None
        row_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0)).row_key
        return next((t for t in self.session.targets if self._key(t) == row_key.value), None)

    def action_add_host(self) -> None:
        self.app.push_screen(HostPrompt("Ping which host? (several: separate them with spaces)"),
                             self._add)

    def _add(self, answer: str | None) -> None:
        for host in (answer or "").replace(",", " ").split():
            if any(t.name == host for t in self.session.targets):
                self.notify(f"{host} is already on the list", severity="warning")
                continue
            self.session.add(host)
        self.refresh_view()

    def action_remove_host(self) -> None:
        target = self.highlighted()
        if target is not None:
            self.session.remove(target)
            self.refresh_view()

    def action_history(self) -> None:
        target = self.highlighted()
        if target is not None:
            self.app.push_screen(HistoryScreen(lambda: target_label(target), target.stats))

    async def action_trace_host(self) -> None:
        target = self.highlighted()
        if target is not None:
            await self.app.trace(target.name)
