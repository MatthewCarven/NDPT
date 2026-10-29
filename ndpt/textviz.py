"""Small text renderings shared by the CLI and the TUI."""

from __future__ import annotations

from collections.abc import Sequence

BLOCKS = "▁▂▃▄▅▆▇█"
ASCII_LEVELS = "_.-~=+*#"


def sparkline(values: Sequence[float | None], *, ascii_only: bool = False) -> str:
    """One character per sample, scaled from 0 to the largest sample; lost samples show as x.

    Scaling from 0 rather than from the smallest sample keeps a steady 20.1-20.4 ms
    line flat instead of making it look wild.
    """
    levels = ASCII_LEVELS if ascii_only else BLOCKS
    lost = "x" if ascii_only else "×"
    top = max((v for v in values if v is not None), default=0.0)
    chars = []
    for value in values:
        if value is None:
            chars.append(lost)
        elif top <= 0:
            chars.append(levels[0])
        else:
            chars.append(levels[min(len(levels) - 1, round(value / top * (len(levels) - 1)))])
    return "".join(chars)


def fmt_ms(value: float | None) -> str:
    if value is None:
        return "-"
    if value < 10:
        return f"{value:.2f}"
    if value < 100:
        return f"{value:.1f}"
    return f"{value:.0f}"


def loss_style(pct: float) -> str:
    if pct == 0:
        return "green"
    if pct < 5:
        return "yellow"
    return "red"
