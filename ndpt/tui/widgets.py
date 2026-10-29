"""Pieces both TUI screens use: a base for live screens, the host prompt, the history view."""

from __future__ import annotations

from collections.abc import Callable

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widget import Widget
from textual.widgets import Input, Label, Static

from ndpt.core.session import Session
from ndpt.core.stats import RollingStats
from ndpt.textviz import bar_chart, fmt_ms, loss_style, sparkline

REFRESH = 0.25      # seconds between redraws of live data
MAX_HISTORY = 60    # samples in a table's history column
MIN_HISTORY = 8     # below this, a history column isn't worth its space
HOST_WIDTH = 36     # the most a host column takes before the history column gets the rest


class SessionScreen(Screen):
    """A screen over one live session: redraws on a timer while it's showing, pauses on space."""

    BINDINGS = [Binding("space", "toggle_pause", "Pause")]

    session: Session | None = None

    def on_mount(self) -> None:
        self.set_interval(REFRESH, self._tick)

    def on_screen_resume(self) -> None:
        self.refresh_view()

    def _tick(self) -> None:
        if self.is_current:  # a hidden screen catches up when it's shown again
            self.refresh_view()

    def refresh_view(self) -> None:
        raise NotImplementedError

    def run_session(self, session: Session) -> None:
        """Run the session on the app's own loop until it's stopped (or the screen goes)."""
        self.run_worker(session.run(), group="session", description=type(session).__name__)

    def action_toggle_pause(self) -> None:
        if self.session is None:
            return
        if self.session.paused:
            self.session.resume()
        else:
            self.session.pause()
        self.refresh_view()


class HostPrompt(ModalScreen[str | None]):
    """Asks for a host; dismisses with what was typed, or None if cancelled or left empty."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, question: str, value: str = "") -> None:
        super().__init__()
        self.question = question
        self.value = value

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.question)
            yield Input(value=self.value, placeholder="a name or address, e.g. 1.1.1.1")
            yield Label("enter: OK   escape: cancel", classes="hint")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip() or None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class HistoryChart(Widget):
    """Recent round-trip times as bars, newest on the right, with the scale at the left."""

    def __init__(self, stats: RollingStats) -> None:
        super().__init__()
        self.stats = stats

    def render(self) -> Text:
        width, height = self.content_size
        rows = max(1, height - 1)  # the bottom line is the caption
        gutter = 7                 # "1234 ┤": fmt_ms stays within 4 characters below 10 s
        shown = self.stats.recent()[-max(1, width - gutter):]
        top = max((v for v in shown if v is not None), default=0.0)
        bars = [bar.rjust(width - gutter) for bar in bar_chart(shown, rows, top)]
        text = Text(no_wrap=True, overflow="crop")
        for i, bar in enumerate(bars):
            label = (fmt_ms(top) if top else "") if i == 0 else "0" if i == rows - 1 else ""
            axis = "┤" if label else "│"
            text.append(f"{label:>{gutter - 2}} {axis}", style="dim")
            line = Text(bar, style="cyan")
            line.highlight_words(["×"], "red")
            text.append_text(line)
            text.append("\n")
        caption = f"the last {len(shown)} probes, newest on the right, ms" if shown else "no probes yet"
        text.append(" " * gutter + caption, style="dim")
        return text


class HistoryScreen(ModalScreen[None]):
    """A bigger view of one host's or hop's recent round-trip times, kept up to date."""

    BINDINGS = [Binding("escape", "close", "Close")]

    def __init__(self, title: Callable[[], Text | str], stats: RollingStats,
                 details: Callable[[], list[Text | str]] | None = None) -> None:
        super().__init__()
        self.title_of = title
        self.stats = stats
        self.details = details

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog history"):
            yield Static(id="history-head")
            yield HistoryChart(self.stats)
            yield Label("escape: close", classes="hint")

    def on_mount(self) -> None:
        self.set_interval(REFRESH, self.refresh_view)
        self.refresh_view()

    def refresh_view(self) -> None:
        head = Text(no_wrap=False)
        title = self.title_of()
        head.append_text(title if isinstance(title, Text) else Text(title))
        head.stylize("bold")
        head.append("\n")
        head.append_text(stats_line(self.stats))
        for line in (self.details() if self.details else []):
            head.append("\n")
            head.append_text(line if isinstance(line, Text) else Text(line))
        self.query_one("#history-head", Static).update(head)
        self.query_one(HistoryChart).refresh()

    def action_close(self) -> None:
        self.dismiss(None)


def stats_line(s: RollingStats) -> Text:
    """Every number we keep for a host or hop, on one line."""
    text = Text()
    text.append(f"sent {s.sent}  received {s.received}  loss ")
    text.append(f"{s.loss_pct:.1f}%", style=loss_style(s.loss_pct) if s.sent else "")
    pairs = [("last", s.last), ("best", s.best), ("avg", s.avg), ("worst", s.worst),
             ("stdev", s.stdev), ("jitter", s.jitter if s.received > 1 else None),
             ("p50", s.percentile(50)), ("p95", s.percentile(95))]
    text.append("".join(f"  {name} {fmt_ms(value)}" for name, value in pairs) + "  (ms)")
    return text


def spark(values: list[float | None]) -> Text:
    """A sparkline with its losses in red."""
    text = Text(sparkline(values), style="cyan")
    text.highlight_words(["×"], "red")
    return text


def heading(name: str) -> Text:
    """A number column's heading, right-aligned over its numbers."""
    return Text(name, justify="right")


def cell(value: Text | str, width: int | None = None, justify: str = "left") -> Text:
    """A table cell: right-justified for numbers, cut to `width` with an ellipsis for names."""
    text = value.copy() if isinstance(value, Text) else Text(value)
    text.no_wrap = True
    if width is not None and text.cell_len > width:
        text.truncate(width, overflow="ellipsis")
    text.justify = justify
    return text


def share_width(total: int, fixed: int, columns: int, longest_host: int,
                max_history: int = 0) -> tuple[int, int]:
    """Widths for the host column and the history column of a DataTable `total` cells wide.

    `fixed` is the width of every other column's content and `columns` the
    number of columns in all; DataTable pads each with a cell either side.
    Host names get up to HOST_WIDTH and the history the rest (at most
    `max_history`, at least MIN_HISTORY). A narrow table loses its history
    before its host names get cut below 10 cells.
    """
    spare = total - fixed - 2 * columns
    host = min(longest_host, HOST_WIDTH, spare - MIN_HISTORY)
    if max_history and host >= min(10, longest_host):
        return host, min(max_history, spare - host)
    return max(10, min(longest_host, spare)), 0
