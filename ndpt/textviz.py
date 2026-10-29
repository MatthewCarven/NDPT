"""Small text renderings shared by the CLI and the TUI."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from rich.text import Text

from ndpt.core.models import ProbeStatus

if TYPE_CHECKING:
    from ndpt.core.models import Hop
    from ndpt.core.trace import TraceSession

BLOCKS = "▁▂▃▄▅▆▇█"
ASCII_LEVELS = "_.-~=+*#"
EIGHTHS = " ▁▂▃▄▅▆▇█"  # 0 to 8 eighths of a cell

_SHORT_STATUS = {ProbeStatus.TIMEOUT: "timeout", ProbeStatus.UNREACHABLE: "unreach",
                 ProbeStatus.ERROR: "error"}


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


def bar_chart(values: Sequence[float | None], height: int, top: float | None = None) -> list[str]:
    """A bar chart `height` rows tall, top row first, one column per sample.

    Bars rise from 0 to `top` (default: the largest sample), in eighths of a
    row. Any answer gets at least a sliver; a lost sample is a × on the bottom row.
    """
    if top is None:
        top = max((v for v in values if v is not None), default=0.0)
    eighths = []
    for value in values:
        if value is None:
            eighths.append(None)
        else:
            scaled = round(value / top * height * 8) if top > 0 else 0
            eighths.append(min(height * 8, max(1, scaled)))
    rows = []
    for row in range(height):
        below = (height - 1 - row) * 8  # eighths taken by the rows under this one
        chars = []
        for e in eighths:
            if e is None:
                chars.append("×" if row == height - 1 else " ")
            else:
                chars.append(EIGHTHS[min(8, max(0, e - below))])
        rows.append("".join(chars))
    return rows


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


def host_label(name: str | None, address: str) -> str:
    return f"{name} ({address})" if name and name != address else address


def hop_label(hop: Hop, session: TraceSession) -> Text | str:
    """The hop's router (by name once its lookup lands), and how many others share the hop."""
    address = hop.address
    if address is None:
        return Text("???", style="dim")
    name = session.resolver.cached(address) if session.lookup_names else None
    label = host_label(name, address)
    if len(hop.responders) > 1:
        label += f" +{len(hop.responders) - 1}"
    return label


def loss_cell(sent: int, pct: float) -> Text | str:
    return Text(f"{pct:.1f}%", style=loss_style(pct)) if sent else "-"


def last_cell(status: ProbeStatus | None, last_rtt: float | None, echo_only: bool = False) -> Text | str:
    """The latest probe: its time if it was answered, else what happened to it.

    A ping only counts an echo reply; a trace hop counts any answer."""
    if status is None:
        return "-"
    if status is ProbeStatus.REPLY or (status.answered and not echo_only):
        return fmt_ms(last_rtt)
    return Text(_SHORT_STATUS.get(status, status.value), style="red")
