"""The trace tab: the mtr table, the route diagram, latency per hop, and one hop over time."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ndpt.core.snapshot import Carried, HopSnapshot, TraceSnapshot, carried_on
from ndpt.gui.bridge import Engine, Settings, TraceRunner
from ndpt.gui.charts import HopChart, LatencyChart
from ndpt.gui.route_graph import RouteGraph
from ndpt.gui.theme import Theme
from ndpt.gui.widgets import dot, last_text, number_table, set_cell
from ndpt.textviz import fmt_ms, host_label

COLUMNS = ("#", "Host", "Loss", "Sent", "Last", "Avg", "Best", "Worst", "StDev", "Jitter")
NO_ANSWER = ("This router never answers traceroute probes. That says nothing about your "
             "traffic, which it forwards as usual.")


def hop_text(hop: HopSnapshot) -> str:
    """The hop's router, by name once known, and how many others share the hop."""
    if hop.address is None:
        return "???"
    label = host_label(hop.name, hop.address)
    if len(hop.responders) > 1:
        label += f" +{len(hop.responders) - 1}"
    return label


class TraceView(QWidget):
    """Traces one host at a time, round after round. A new host starts a new trace."""

    route_changed = Signal(str)  # a path event after the first round, for the status bar

    def __init__(self, engine: Engine, settings: Settings, theme: Theme) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.theme = theme
        self.runner: TraceRunner | None = None
        self.snapshot: TraceSnapshot | None = None
        self.carried: list[Carried] = []
        self.host: str | None = None
        self._stale = False  # a snapshot came in while hidden

        self.entry = QLineEdit(placeholderText="host to trace, e.g. 1.1.1.1")
        self.entry.returnPressed.connect(self._start_clicked)
        self.start_button = QPushButton("Start")
        self.start_button.clicked.connect(self._start_clicked)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._pause)
        self.status = QLabel()
        self.cannot = QLabel()  # why this prober can't trace, instead of hiding the tab
        self.cannot.setWordWrap(True)
        self.cannot.setStyleSheet(f"color: {theme.critical}; font-weight: bold;")
        self.cannot.hide()

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Trace"))
        bar.addWidget(self.entry, 1)
        bar.addWidget(self.start_button)
        bar.addWidget(self.pause_button)
        bar.addWidget(self.status, 2)

        self.table = number_table(COLUMNS, stretch=1)
        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.hop_chart = HopChart(theme)
        self.hop_chart.hop_clicked.connect(self.select_hop)
        self.history = LatencyChart(theme, "select a hop to see its latency over time")
        self.graph = RouteGraph(theme)
        self.graph.hop_clicked.connect(self.select_hop)
        self.notes = QListWidget()
        self.notes.setWordWrap(True)

        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.table)
        left.addWidget(self.notes)
        left.setSizes([340, 110])
        charts = QSplitter(Qt.Orientation.Vertical)
        charts.addWidget(self.hop_chart)
        charts.addWidget(self.history)
        upper = QSplitter(Qt.Orientation.Horizontal)
        upper.addWidget(left)
        upper.addWidget(charts)
        upper.setSizes([700, 560])
        main = QSplitter(Qt.Orientation.Vertical)
        main.addWidget(upper)
        main.addWidget(self.graph)  # the whole width: routes are long
        main.setSizes([470, 260])
        layout = QVBoxLayout(self)
        layout.addLayout(bar)
        layout.addWidget(self.cannot)
        layout.addWidget(main, 1)
        self._explain()

    # --- the session ---

    def can_trace(self) -> str | None:
        """None if the engine's prober can trace, else why not."""
        prober = self.engine.prober
        if prober.supports_ttl:
            return None
        return (f"The {prober.name.upper()} prober can't trace: it can't set a probe's TTL, so no "
                "router on the way ever answers. Choose ICMP in Settings to trace; the Ping tab "
                f"works with {prober.name.upper()}.")

    def trace(self, host: str) -> bool:
        """Trace `host` from scratch, stopping any trace running. False if this prober can't."""
        self.stop()
        self.host = host
        self.entry.setText(host)
        self.snapshot = None
        self.carried = []
        self.table.setRowCount(0)
        self.notes.clear()
        self.history.set_series([])
        self.hop_chart.set_hops([], [], None)
        self.graph.clear_trace()
        self.pause_button.setChecked(False)
        if not self._explain():
            self.status.setText("")
            return False
        self.runner = self.engine.trace(host, self.settings)
        self.runner.updated.connect(self._show)
        self.runner.event.connect(self._event)
        self.runner.finished.connect(self._finished)
        self.runner.start()
        self.status.setText(f"tracing {host}...")
        self._buttons()
        return True

    def restart(self, settings: Settings, again: bool) -> None:
        """New settings (or a new prober). `again`: trace the same host again from scratch."""
        self.settings = settings
        self.stop()
        if again and self.host:
            self.trace(self.host)
        else:
            self._explain()

    def _explain(self) -> bool:
        """Say why this prober can't trace, if it can't. True if it can."""
        why = self.can_trace()
        self.cannot.setText(why or "")
        self.cannot.setVisible(why is not None)
        self._buttons()
        return why is None

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()
            self.runner = None
        self._buttons()

    def _start_clicked(self) -> None:
        if self.runner is not None:
            self.stop()
            return
        host = self.entry.text().strip()
        if host:
            self.trace(host)

    def _pause(self, paused: bool) -> None:
        if self.runner is not None:
            (self.runner.pause if paused else self.runner.resume)()
        self.pause_button.setText("Resume" if paused else "Pause")

    def _buttons(self) -> None:
        running = self.runner is not None
        self.start_button.setText("Stop" if running else "Start")
        self.start_button.setEnabled(running or self.can_trace() is None)
        self.pause_button.setEnabled(running)

    def _finished(self, runner: TraceRunner) -> None:
        if runner is self.runner:  # it ended by itself: a name that won't resolve
            self.runner = None
            self._buttons()

    def _event(self, runner: TraceRunner, text: str, round_no: int) -> None:
        if runner is self.runner and round_no > 1:
            self.route_changed.emit(text)

    # --- selecting a hop ---

    def selected_ttl(self) -> int | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows or self.snapshot is None or rows[0].row() >= len(self.snapshot.hops):
            return None
        return self.snapshot.hops[rows[0].row()].ttl

    def select_hop(self, ttl: int) -> None:
        if self.snapshot is None:
            return
        for row, hop in enumerate(self.snapshot.hops):
            if hop.ttl == ttl:
                self.table.selectRow(row)
                return

    def _selection_changed(self) -> None:
        if self.snapshot is not None:
            self._draw_selected()

    def _draw_selected(self) -> None:
        snapshot, ttl = self.snapshot, self.selected_ttl()
        self.hop_chart.set_hops(snapshot.hops, self.carried, snapshot.dest_ttl, ttl)
        self.graph.show_trace(snapshot, self.carried, ttl)
        hop = next((h for h in snapshot.hops if h.ttl == ttl), None)
        title = self.history.getPlotItem()
        if hop is None:
            title.setTitle("select a hop to see its latency over time", color=self.theme.secondary,
                           size="10pt")
            self.history.set_series([])
            return
        title.setTitle(f"hop {hop.ttl}: {hop_text(hop)}, ms over time (lost: red ticks)",
                       color=self.theme.secondary, size="10pt")
        self.history.set_series([(hop.ttl, self.theme.series[0], hop.stats.history)])

    # --- drawing ---

    def _show(self, runner: TraceRunner, snapshot: TraceSnapshot) -> None:
        if runner is not self.runner:
            return  # a stopped trace's last word
        self.snapshot = snapshot
        self.carried = carried_on(snapshot.hops)
        self._stale = self.isHidden()  # another tab is showing: draw when this one is
        if not self._stale:
            self._draw(snapshot)

    def catch_up(self) -> None:
        """This tab is showing now: draw the latest snapshot, if it came in while hidden."""
        if self._stale and self.snapshot is not None:
            self._stale = False
            self._draw(self.snapshot)

    def _draw(self, snapshot: TraceSnapshot) -> None:
        self.history.span = max(10.0, 120 * snapshot.interval)
        self._status(snapshot)
        self._fill_table(snapshot)
        self._fill_notes(snapshot)
        if self.selected_ttl() is None and snapshot.dest_ttl is not None:
            self.select_hop(snapshot.dest_ttl)  # draws it, through the selection's signal
            return
        self._draw_selected()

    def _status(self, snapshot: TraceSnapshot) -> None:
        if snapshot.error:
            self.status.setText(snapshot.error)
            self.status.setStyleSheet(f"color: {self.theme.critical};")
            return
        self.status.setStyleSheet("")
        target = snapshot.host
        if snapshot.address and snapshot.address != snapshot.host:
            target += f" ({snapshot.address})"
        paused = ", paused" if snapshot.paused else ""
        self.status.setText(f"to {target}, round {snapshot.round}, every {snapshot.interval:g}s{paused}")

    def _fill_table(self, snapshot: TraceSnapshot) -> None:
        table, theme = self.table, self.theme
        table.setRowCount(len(snapshot.hops))
        for row, (hop, carried) in enumerate(zip(snapshot.hops, self.carried)):
            s = hop.stats
            dest = hop.ttl == snapshot.dest_ttl
            set_cell(table, row, 0, str(hop.ttl))
            set_cell(table, row, 1, hop_text(hop), number=False,
                     tooltip="\n".join(f"{r.name or r.address}: {r.count} answers"
                                       for r in hop.responders) or NO_ANSWER,
                     colour=None if hop.responders else theme.muted)
            loss = f"{s.loss_pct:.1f}%" if s.sent else "-"
            if not hop.responders:
                set_cell(table, row, 2, loss, colour=theme.muted, tooltip=NO_ANSWER)
            elif carried.loss_stops_here:
                set_cell(table, row, 2, loss, icon=dot(theme.loss_colour(carried.loss_pct), True),
                         colour=theme.muted,
                         tooltip=f"Only {carried.loss_pct:.1f}% of this loss carries on to the hops "
                                 "after it: the rest is the router rate-limiting its replies, not "
                                 "lost traffic.")
            else:
                set_cell(table, row, 2, loss, icon=dot(theme.loss_colour(carried.loss_pct)))
            if carried.slow_to_reply:
                set_cell(table, row, 5, fmt_ms(s.avg), colour=theme.muted,
                         tooltip=f"Only {fmt_ms(carried.avg)} ms carries on to the hops after it: "
                                 "this router is slow to reply, not slow to forward.")
            else:
                set_cell(table, row, 5, fmt_ms(s.avg))
            cells = {3: str(s.sent), 4: last_text(hop.last_status, s.last), 6: fmt_ms(s.best),
                     7: fmt_ms(s.worst), 8: fmt_ms(s.stdev), 9: fmt_ms(s.jitter)}
            for column, text in cells.items():
                set_cell(table, row, column, text)
            for column in range(len(COLUMNS)):
                item = table.item(row, column)
                if item.font().bold() != dest:
                    font = QFont(item.font())
                    font.setBold(dest)
                    item.setFont(font)

    def _fill_notes(self, snapshot: TraceSnapshot) -> None:
        lines = [(note, True) for note in snapshot.notes] + [(e, False) for e in snapshot.events]
        if [(self.notes.item(i).text(), bool(self.notes.item(i).data(Qt.ItemDataRole.UserRole)))
                for i in range(self.notes.count())] == [(f"note: {t}" if n else t, n) for t, n in lines]:
            return
        self.notes.clear()
        for text, is_note in lines:
            item = QListWidgetItem(f"note: {text}" if is_note else text)
            item.setData(Qt.ItemDataRole.UserRole, is_note)
            if is_note:
                item.setIcon(dot(self.theme.warning))
            else:
                item.setForeground(self.theme.qcolor(self.theme.secondary))
            self.notes.addItem(item)
        self.notes.scrollToBottom()
