"""The ping tab: hosts side by side, as a live chart, a histogram and a table of numbers."""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QSplitter, QVBoxLayout, QWidget)

from ndpt.core.snapshot import PingSnapshot, TargetSnapshot
from ndpt.gui.bridge import Engine, PingRunner, Settings
from ndpt.gui.charts import HistogramChart, LatencyChart
from ndpt.gui.theme import Theme
from ndpt.gui.widgets import dot, last_text, number_table, pace_buttons, set_cell, swatch
from ndpt.textviz import fmt_ms, host_label

COLUMNS = ("Host", "Sent", "Loss", "Last", "Avg", "Best", "Worst", "StDev", "Jitter", "p95")
KEY = Qt.ItemDataRole.UserRole


def target_label(target: TargetSnapshot) -> str:
    return host_label(target.name, target.address) if target.address else target.name


class PingView(QWidget):
    """Pings every host on its list. The list can change while it runs."""

    trace_requested = Signal(str)  # a host to trace, from the Trace button

    def __init__(self, engine: Engine, settings: Settings, theme: Theme,
                 hosts: Sequence[str] = ()) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.theme = theme
        self.runner: PingRunner | None = None
        self.snapshot: PingSnapshot | None = None
        self._stale = False  # a snapshot came in while hidden
        self.names = list(dict.fromkeys(hosts))  # what the session is pinging, as far as we know
        self._slots: dict[str, int] = {}         # host name -> its colour, for as long as it stays

        self.entry = QLineEdit(placeholderText="host, e.g. 1.1.1.1")
        self.entry.setToolTip("Several hosts: separate them with spaces")
        self.entry.returnPressed.connect(self.add_from_entry)
        self.add_button = QPushButton("Add")
        self.add_button.clicked.connect(self.add_from_entry)
        self.host_list = QListWidget()
        self.host_list.currentItemChanged.connect(self._selection_changed)
        self.remove_button = QPushButton("Remove")
        self.remove_button.clicked.connect(self.remove_selected)
        self.trace_button = QPushButton("Trace")
        self.trace_button.setToolTip("Trace the route to the selected host")
        self.trace_button.clicked.connect(self._trace_selected)
        self.pause_button = QPushButton("Pause")
        self.pause_button.setCheckable(True)
        self.pause_button.toggled.connect(self._pause)
        self.slower_button, self.faster_button = pace_buttons(self.slower, self.faster)
        self.status = QLabel()
        self.status.setWordWrap(True)

        entry_row = QHBoxLayout()
        entry_row.addWidget(self.entry)
        entry_row.addWidget(self.add_button)
        buttons = QHBoxLayout()
        buttons.addWidget(self.remove_button)
        buttons.addWidget(self.trace_button)
        pace = QHBoxLayout()
        pace.addWidget(self.pause_button)
        pace.addWidget(self.slower_button)
        pace.addWidget(self.faster_button)
        side = QVBoxLayout()
        side.addWidget(QLabel("Hosts"))
        side.addLayout(entry_row)
        side.addWidget(self.host_list, 1)
        side.addLayout(buttons)
        side.addLayout(pace)
        side.addWidget(self.status)
        panel = QWidget()
        panel.setLayout(side)
        panel.setMaximumWidth(320)

        self.chart = LatencyChart(theme, "round-trip time, ms (lost probes: red ticks)")
        self.histogram = HistogramChart(theme)
        self.table = number_table(COLUMNS)
        lower = QSplitter(Qt.Orientation.Horizontal)
        lower.addWidget(self.table)
        lower.addWidget(self.histogram)
        lower.setSizes([620, 380])
        right = QSplitter(Qt.Orientation.Vertical)
        right.addWidget(self.chart)
        right.addWidget(lower)
        right.setSizes([420, 300])
        layout = QHBoxLayout(self)
        layout.addWidget(panel)
        layout.addWidget(right, 1)
        self._buttons()

    # --- the session ---

    def start(self, settings: Settings | None = None) -> None:
        """Start pinging the list, from scratch (new settings, or a new prober)."""
        self.stop()
        if settings is not None:
            self.settings = settings
        self.chart.span = max(10.0, 120 * self.settings.interval)  # the last 120 probes or so
        self.runner = self.engine.ping(self.names, self.settings)
        self.runner.updated.connect(self._show)
        self.runner.start()
        self.pause_button.setChecked(False)

    def stop(self) -> None:
        if self.runner is not None:
            self.runner.stop()
            self.runner = None

    def add_from_entry(self) -> None:
        hosts = self.entry.text().replace(",", " ").split()
        self.entry.clear()
        for host in hosts:
            self.add(host)

    def add(self, host: str) -> bool:
        if host in self.names:
            self.status.setText(f"{host} is already on the list")
            return False
        self.names.append(host)
        if self.runner is not None:
            self.runner.add(host)
        return True

    def remove_selected(self) -> None:
        item = self.host_list.currentItem()
        if item is None or self.runner is None:
            return
        key = item.data(KEY)
        target = next((t for t in self.snapshot.targets if t.key == key), None) if self.snapshot else None
        if target is None:
            return
        self.runner.remove(key)
        self.names.remove(target.name)
        self._slots.pop(target.name, None)
        self.host_list.takeItem(self.host_list.row(item))

    def selected(self) -> TargetSnapshot | None:
        item = self.host_list.currentItem()
        if item is None or self.snapshot is None:
            return None
        return next((t for t in self.snapshot.targets if t.key == item.data(KEY)), None)

    def _trace_selected(self) -> None:
        target = self.selected()
        if target is not None:
            self.trace_requested.emit(target.name)

    def _pause(self, paused: bool) -> None:
        if self.runner is not None:
            (self.runner.pause if paused else self.runner.resume)()
        self.pause_button.setText("Resume" if paused else "Pause")

    def slower(self) -> None:
        if self.runner is not None:
            self.runner.slower()

    def faster(self) -> None:
        if self.runner is not None:
            self.runner.faster()

    def _selection_changed(self) -> None:
        self._buttons()

    def _buttons(self) -> None:
        chosen = self.host_list.currentItem() is not None
        self.remove_button.setEnabled(chosen)
        self.trace_button.setEnabled(chosen)

    def colour(self, name: str) -> str:
        """A host keeps its colour while it's on the list; a removed host's colour goes to the next one."""
        slot = self._slots.get(name)
        if slot is None:
            used = set(self._slots.values())
            slot = self._slots[name] = next(i for i in range(len(self._slots) + 1) if i not in used)
        return self.theme.series_colour(slot)

    # --- drawing ---

    def _show(self, runner: PingRunner, snapshot: PingSnapshot) -> None:
        if runner is not self.runner:
            return  # a stopped session's last word, or the session before a restart
        self.snapshot = snapshot
        self._stale = self.isHidden()  # another tab is showing: draw when this one is
        if not self._stale:
            self._draw(snapshot)

    def catch_up(self) -> None:
        """This tab is showing now: draw the latest snapshot, if it came in while hidden."""
        if self._stale and self.snapshot is not None:
            self._stale = False
            self._draw(self.snapshot)

    def _draw(self, snapshot: PingSnapshot) -> None:
        targets = [t for t in snapshot.targets if t.name in self.names]
        self._fill_list(targets)
        self._fill_table(targets)
        live = [t for t in targets if not t.error]
        self.chart.set_series([(t.name, self.colour(t.name), t.stats.history) for t in live])
        self.histogram.set_series([(t.name, self.colour(t.name),
                                    [rtt for _, rtt in t.stats.history if rtt is not None])
                                   for t in live])
        self.chart.span = max(10.0, 120 * snapshot.interval)  # follows + and -
        self.faster_button.setEnabled(snapshot.interval > snapshot.base_interval)
        status = f"{snapshot.prober} every {snapshot.interval:g}s"
        self.status.setText(status + (", paused" if snapshot.paused else ""))

    def _fill_list(self, targets: list[TargetSnapshot]) -> None:
        current = self.host_list.currentItem()
        chosen = current.data(KEY) if current is not None else None
        rows = [(t.key, target_label(t), t.error) for t in targets]
        if rows != [(self.host_list.item(i).data(KEY), self.host_list.item(i).text(),
                     self.host_list.item(i).toolTip() or None) for i in range(self.host_list.count())]:
            self.host_list.blockSignals(True)
            self.host_list.clear()
            for target, (key, label, error) in zip(targets, rows):
                item = QListWidgetItem(swatch(self.colour(target.name)), label)
                item.setData(KEY, key)
                if error:
                    item.setToolTip(error)
                    item.setForeground(self.theme.qcolor(self.theme.critical))
                self.host_list.addItem(item)
                if key == chosen:
                    self.host_list.setCurrentItem(item)
            self.host_list.blockSignals(False)
        self._buttons()

    def _fill_table(self, targets: list[TargetSnapshot]) -> None:
        table = self.table
        table.setRowCount(len(targets))
        for row, target in enumerate(targets):
            icon = swatch(self.colour(target.name))
            if target.error:
                set_cell(table, row, 0, f"{target.name}: {target.error}", number=False, icon=icon,
                         colour=self.theme.critical)
                for column in range(1, len(COLUMNS)):
                    set_cell(table, row, column, "-")
                continue
            set_cell(table, row, 0, target_label(target), number=False, icon=icon)
            s = target.stats
            loss = f"{s.loss_pct:.1f}%" if s.sent else "-"
            set_cell(table, row, 2, loss, icon=dot(self.theme.loss_colour(s.loss_pct)) if s.sent else None)
            cells = {1: str(s.sent), 3: last_text(target.last_status, s.last, echo_only=True),
                     4: fmt_ms(s.avg), 5: fmt_ms(s.best), 6: fmt_ms(s.worst), 7: fmt_ms(s.stdev),
                     8: fmt_ms(s.jitter), 9: fmt_ms(s.p95)}
            for column, text in cells.items():
                set_cell(table, row, column, text)
