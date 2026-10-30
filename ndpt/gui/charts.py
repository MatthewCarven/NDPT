"""The pyqtgraph charts: live latency and the latency histogram."""

from __future__ import annotations

import math
import time
from collections.abc import Hashable, Sequence

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer

from ndpt.gui.theme import Theme

SCROLL_MS = 100  # how often a live chart moves along


def style(widget: pg.PlotWidget, theme: Theme, title: str, left: str,
          bottom: str | None = None) -> pg.PlotItem:
    """A quiet, fixed chart: no mouse zoom or menu, hairline axes, a faint grid across."""
    item = widget.getPlotItem()
    item.setMenuEnabled(False)
    item.setMouseEnabled(x=False, y=False)
    item.hideButtons()
    item.setTitle(title, color=theme.secondary, size="10pt")
    item.setLabel("left", left, color=theme.muted)
    if bottom:
        item.setLabel("bottom", bottom, color=theme.muted)
    for name in ("left", "bottom"):
        axis = item.getAxis(name)
        axis.setPen(pg.mkPen(theme.grid))
        axis.setTextPen(pg.mkPen(theme.muted))
    item.showGrid(x=False, y=True, alpha=0.25)
    return item


def top_of(values: Sequence[float]) -> float:
    """A y-axis top with a little room over the largest value. Charts start at 0, always."""
    return max(1.0, max(values, default=0.0) * 1.15)


class ClockAxis(pg.AxisItem):
    """Clock times (HH:MM:SS) on whole-second ticks, about one label per 90 pixels."""

    STEPS = (1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600)

    def tickValues(self, minVal: float, maxVal: float, size: float) -> list:
        labels = max(2.0, size / 90)
        step = next((s for s in self.STEPS if (maxVal - minVal) / s <= labels), self.STEPS[-1])
        return [(step, list(np.arange(math.ceil(minVal / step) * step, maxVal, step)))]

    def tickStrings(self, values: list[float], scale: float, spacing: float) -> list[str]:
        return [time.strftime("%H:%M:%S", time.localtime(v)) for v in values]


class LatencyChart(pg.PlotWidget):
    """Round-trip times against the clock, scrolling, newest on the right.

    A gap in a line is a lost probe, and each lost probe is a red tick along the
    bottom. The y axis starts at 0, so a steady 20.1-20.4 ms line looks steady.
    """

    def __init__(self, theme: Theme, title: str, span: float = 120.0) -> None:
        super().__init__(background=theme.surface, axisItems={"bottom": ClockAxis("bottom")})
        self.theme = theme
        self.span = span
        style(self, theme, title, "ms")
        self.curves: dict[Hashable, pg.PlotDataItem] = {}
        self.lost = pg.ScatterPlotItem(symbol="|", size=18, pen=pg.mkPen(theme.critical, width=2),
                                       brush=None)
        self.lost.setZValue(10)
        self.addItem(self.lost)
        self._scroll()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._scroll)
        self._timer.start(SCROLL_MS)

    def set_series(self, series: Sequence[tuple[Hashable, str, Sequence[tuple[float, float | None]]]]
                   ) -> None:
        """Show these series and only these: (key, colour, history of (time sent, rtt or None))."""
        keys = {key for key, _, _ in series}
        for key in [k for k in self.curves if k not in keys]:
            self.removeItem(self.curves.pop(key))
        lost: list[float] = []
        shown: list[float] = []
        since = time.time() - self.span
        for key, colour, history in series:
            curve = self.curves.get(key)
            if curve is None:
                curve = self.curves[key] = pg.PlotDataItem()
                self.addItem(curve)
            xs = np.fromiter((t for t, _ in history), float, len(history))
            ys = np.fromiter((math.nan if rtt is None else rtt for _, rtt in history), float,
                             len(history))
            # Dots as well as the line, so an answer between two losses still shows.
            curve.setData(xs, ys, connect="finite", pen=pg.mkPen(colour, width=2), symbol="o",
                          symbolSize=5, symbolPen=None, symbolBrush=pg.mkBrush(colour))
            lost += [t for t, rtt in history if rtt is None]
            shown += [rtt for t, rtt in history if rtt is not None and t >= since]
        self.lost.setData(lost, [0.0] * len(lost))
        self.setYRange(0, top_of(shown), padding=0)

    def _scroll(self) -> None:
        now = time.time()
        self.setXRange(now - self.span, now, padding=0)


class HistogramChart(pg.PlotWidget):
    """How the recent round-trip times spread, one outlined step shape per host."""

    def __init__(self, theme: Theme) -> None:
        super().__init__(background=theme.surface)
        self.theme = theme
        style(self, theme, "latency histogram, recent probes", "probes", "ms")
        self.curves: dict[Hashable, pg.PlotCurveItem] = {}

    def set_series(self, series: Sequence[tuple[Hashable, str, Sequence[float]]]) -> None:
        """(key, colour, round-trip times) for each host, all binned alike."""
        keys = {key for key, _, _ in series}
        for key in [k for k in self.curves if k not in keys]:
            self.removeItem(self.curves.pop(key))
        values = [v for _, _, vs in series for v in vs]
        if not values:
            for curve in self.curves.values():
                curve.setData([], [])
            return
        lo, hi = min(values), max(values)
        if hi - lo < 1.0:  # a LAN host: give the bins a millisecond to spread over
            lo, hi = max(0.0, lo - 0.5), hi + 0.5
        edges = np.histogram_bin_edges(values, bins=min(40, max(8, int(math.sqrt(len(values))))),
                                       range=(lo, hi))
        top = 0
        for key, colour, vs in series:
            counts = np.histogram(vs, edges)[0] if vs else np.zeros(len(edges) - 1, int)
            top = max(top, int(counts.max(initial=0)))
            curve = self.curves.get(key)
            if curve is None:
                curve = self.curves[key] = pg.PlotCurveItem()
                self.addItem(curve)
            curve.setData(edges, counts, stepMode="center", fillLevel=0,
                          pen=pg.mkPen(colour, width=2), brush=self.theme.qcolor(colour, 30))
        self.setXRange(edges[0], edges[-1], padding=0.02)
        self.setYRange(0, max(1, top) * 1.15, padding=0)
