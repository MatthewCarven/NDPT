"""Colours for the charts and the route diagram, light or dark to match the system."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication

# Status colours, the same in both modes. Each ships with a label beside it, never alone.
GOOD = "#0ca30c"
WARNING = "#fab219"
CRITICAL = "#d03b3b"

# One blue, light to dark, for magnitudes (latency).
BLUES = ("#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6",
         "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b")  # steps 100 to 700


@dataclass(frozen=True)
class Theme:
    dark: bool
    surface: str
    ink: str
    secondary: str
    muted: str
    grid: str
    series: tuple[str, ...]   # one per host, in this order; colour follows the host
    latency: tuple[str, ...]  # little to a lot, every step visible on the surface
    bar: str                  # an intermediate hop's average
    bar_faint: str            # an average that doesn't carry on to the hops after it
    bar_dest: str             # the destination's: a step further from the surface than `bar`
    good: str = GOOD
    warning: str = WARNING
    critical: str = CRITICAL

    def series_colour(self, slot: int) -> str:
        return self.series[slot % len(self.series)]

    def loss_colour(self, pct: float) -> str:
        """The same thresholds as the CLI and TUI: none, under 5%, 5% or more."""
        if pct == 0:
            return self.good
        return self.warning if pct < 5 else self.critical

    def latency_colour(self, ms: float, top: float = 200.0) -> str:
        """A step of the blue ramp, on a log scale from 0 to `top` ms (and past it, the darkest)."""
        x = math.log1p(max(0.0, ms)) / math.log1p(top)
        return self.latency[min(len(self.latency) - 1, int(x * len(self.latency)))]

    def qcolor(self, name: str, alpha: int = 255) -> QColor:
        colour = QColor(name)
        colour.setAlpha(alpha)
        return colour


LIGHT = Theme(
    dark=False, surface="#fcfcfb", ink="#0b0b0b", secondary="#52514e", muted="#898781",
    grid="#e1e0d9",
    series=("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"),
    latency=BLUES[3:], bar=BLUES[4], bar_faint=BLUES[1], bar_dest=BLUES[8],
)
DARK = Theme(
    dark=True, surface="#1a1a19", ink="#f0efec", secondary="#c3c2b7", muted="#898781",
    grid="#2c2c2a",
    series=("#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"),
    latency=BLUES[10::-1], bar=BLUES[8], bar_faint=BLUES[11], bar_dest=BLUES[3],
)


def current() -> Theme:
    """Dark if the system asks for it, light otherwise (and offscreen)."""
    app = QGuiApplication.instance()
    if app is not None and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return DARK
    return LIGHT
