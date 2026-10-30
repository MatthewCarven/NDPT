"""Small Qt pieces both tabs use: tables of numbers, colour swatches, status dots."""

from __future__ import annotations

import functools
from collections.abc import Sequence

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem

from ndpt.core.models import ProbeStatus
from ndpt.textviz import fmt_ms

_SHORT_STATUS = {ProbeStatus.TIMEOUT: "timeout", ProbeStatus.UNREACHABLE: "unreach",
                 ProbeStatus.ERROR: "error"}


@functools.cache
def swatch(colour: str, size: int = 12) -> QIcon:
    """A series colour, for a host's row: the mark beside the text carries the identity."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colour))
    painter.drawRoundedRect(QRectF(1, 1, size - 2, size - 2), 3, 3)
    painter.end()
    return QIcon(pixmap)


@functools.cache
def dot(colour: str, hollow: bool = False, size: int = 10) -> QIcon:
    """A status dot beside a number. Hollow: what's shown here doesn't carry on (see carried_on)."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    if hollow:
        painter.setPen(QPen(QColor(colour), 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
    else:
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(colour)))
    painter.drawEllipse(QRectF(1.5, 1.5, size - 3, size - 3))
    painter.end()
    return QIcon(pixmap)


def number_table(columns: Sequence[str], stretch: int = 0) -> QTableWidget:
    """A read-only table of whole rows; column `stretch` takes the spare width."""
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels(list(columns))
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.setWordWrap(False)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(stretch, QHeaderView.ResizeMode.Stretch)
    for column in range(len(columns)):
        if column != stretch:
            item = table.horizontalHeaderItem(column)
            item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    return table


def set_cell(table: QTableWidget, row: int, column: int, text: str, *, number: bool = True,
             icon: QIcon | None = None, tooltip: str = "", colour: str | None = None) -> None:
    """Fill one cell, reusing its item: rebuilding items would lose the selection."""
    item = table.item(row, column)
    if item is None:
        item = QTableWidgetItem()
        table.setItem(row, column, item)
    if item.text() != text:
        item.setText(text)
    item.setTextAlignment((Qt.AlignmentFlag.AlignRight if number else Qt.AlignmentFlag.AlignLeft)
                          | Qt.AlignmentFlag.AlignVCenter)
    item.setIcon(icon if icon is not None else QIcon())
    item.setToolTip(tooltip)
    item.setData(Qt.ItemDataRole.ForegroundRole, QColor(colour) if colour else None)


def last_text(status: ProbeStatus | None, rtt: float | None, echo_only: bool = False) -> str:
    """The latest probe: its time if answered, else what happened (see textviz.last_cell)."""
    if status is None:
        return "-"
    if status is ProbeStatus.REPLY or (status.answered and not echo_only):
        return fmt_ms(rtt)
    return _SHORT_STATUS.get(status, status.value)
