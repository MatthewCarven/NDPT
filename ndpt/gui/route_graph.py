"""The route diagram: hops left to right, nodes coloured by loss, edges by latency added.

Both colours follow `carried_on`: a node shows the loss that carries on to the
hops after it, and an edge the latency added on that link that carries on. So a
router that's slow to answer traceroute, or rate-limits its answers, doesn't
paint itself red: only the destination's numbers are taken as they come.
"""

from __future__ import annotations

from collections.abc import Sequence

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QMouseEvent, QPainter, QPen, QResizeEvent
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView)

from ndpt.core.snapshot import Carried, HopSnapshot, TraceSnapshot
from ndpt.gui.theme import Theme
from ndpt.textviz import fmt_ms

COLUMN = 150     # the least room between hops, in pixels
ROW = 58         # between the routers sharing a load-balanced hop
RADIUS = 12
MARGIN = 70
MAX_SHOWN = 4    # routers drawn per hop; past that, "+N more"
LABEL_CHARS = 20  # a router's name under its node; the tooltip has it whole
TTL_KEY = 0      # QGraphicsItem.data key holding a node's hop


def elide(text: str, chars: int = LABEL_CHARS) -> str:
    return text if len(text) <= chars else text[:chars - 1] + "…"


class RouteGraph(QGraphicsView):
    """Draws a trace snapshot. Clicking a router selects its hop."""

    hop_clicked = Signal(int)

    def __init__(self, theme: Theme) -> None:
        super().__init__()
        self.theme = theme
        self.setScene(QGraphicsScene(self))
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setBackgroundBrush(QColor(theme.surface))
        self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.snapshot: TraceSnapshot | None = None
        self.carried: list[Carried] = []
        self.selected: int | None = None
        self.nodes: dict[int, list[QGraphicsEllipseItem]] = {}  # hop -> its routers' circles
        self._small = QFont(self.font())
        self._small.setPointSizeF(max(7.0, self.font().pointSizeF() - 1))

    def show_trace(self, snapshot: TraceSnapshot, carried: Sequence[Carried],
                   selected: int | None = None) -> None:
        self.snapshot, self.carried, self.selected = snapshot, list(carried), selected
        self._draw()

    def clear_trace(self) -> None:
        self.snapshot, self.carried, self.selected = None, [], None
        self._draw()

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._draw()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        for item in self.items(event.position().toPoint()):
            ttl = item.data(TTL_KEY)
            if ttl is not None:
                self.hop_clicked.emit(int(ttl))
                return
        super().mousePressEvent(event)

    # --- drawing ---

    def _draw(self) -> None:
        scene = self.scene()
        scene.clear()
        self.nodes = {}
        snapshot = self.snapshot
        if snapshot is None or not snapshot.hops:
            self._text("no trace yet", QPointF(0, 0), self.theme.muted)
            scene.setSceneRect(scene.itemsBoundingRect().adjusted(-20, -20, 20, 20))
            return
        hops = snapshot.hops
        spacing = max(COLUMN, (self.viewport().width() - 2 * MARGIN) / len(hops))
        columns = [[QPointF(MARGIN, 0.0)]]  # this computer
        for i, hop in enumerate(hops, start=1):
            shown = max(1, min(len(hop.responders), MAX_SHOWN))
            columns.append([QPointF(MARGIN + i * spacing, (j - (shown - 1) / 2) * ROW)
                            for j in range(shown)])

        self._source(columns[0][0])
        previous_avg = 0.0  # the latency that carries on to the last hop that answered
        for i, (hop, carried) in enumerate(zip(hops, self.carried), start=1):
            if carried.avg is not None:
                added = max(0.0, carried.avg - previous_avg)
                self._edges(columns[i - 1], columns[i], self.theme.latency_colour(added),
                            f"+{fmt_ms(added)} ms", f"{fmt_ms(added)} ms added on the way to hop "
                            f"{hop.ttl} (latency that carries on to the hops after it)")
                previous_avg = carried.avg
            else:
                self._edges(columns[i - 1], columns[i], None, "", "")
            self._hop(hop, carried, columns[i], dest=hop.ttl == snapshot.dest_ttl)
        self._legend(QPointF(MARGIN - RADIUS, max(p.y() for c in columns for p in c) + 80))
        scene.setSceneRect(scene.itemsBoundingRect().adjusted(-10, -10, 10, 10))

    def _source(self, at: QPointF) -> None:
        circle = self.scene().addEllipse(QRectF(at.x() - RADIUS, at.y() - RADIUS, 2 * RADIUS,
                                                2 * RADIUS), QPen(QColor(self.theme.secondary), 2),
                                         QBrush(QColor(self.theme.surface)))
        circle.setZValue(2)
        self._text("this computer", QPointF(at.x(), at.y() + RADIUS + 4), self.theme.secondary)

    def _edges(self, starts: list[QPointF], ends: list[QPointF], colour: str | None, label: str,
               tooltip: str) -> None:
        """Lines from every router of one hop to every router of the next.

        `colour` None: the hop at the far end never answers, so there's nothing to colour by.
        """
        if colour is None:
            pen = QPen(QColor(self.theme.muted), 1.5, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(colour), 3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        for a in starts:
            for b in ends:
                line = self.scene().addLine(a.x(), a.y(), b.x(), b.y(), pen)
                line.setToolTip(tooltip)
                line.setZValue(1)
        if label:
            mid = QPointF((starts[0].x() + ends[0].x()) / 2,
                          min(p.y() for p in (*starts, *ends)) - RADIUS - 20)
            self._text(label, mid, self.theme.secondary, small=True)

    def _hop(self, hop: HopSnapshot, carried: Carried, at: list[QPointF], dest: bool) -> None:
        theme = self.theme
        s = hop.stats
        top = min(p.y() for p in at)
        self._text(f"hop {hop.ttl}", QPointF(at[0].x(), top - RADIUS - 38), theme.muted, small=True)
        circles = self.nodes[hop.ttl] = []
        if not hop.responders:
            circle = self._circle(at[0], hop.ttl, None, dashed=True)
            circle.setToolTip(f"hop {hop.ttl}: no answer to {s.sent} probes. Some routers never "
                              "answer traceroute; that says nothing about your traffic.")
            circles.append(circle)
            self._text("???", QPointF(at[0].x(), at[0].y() + RADIUS + 4), theme.muted)
            return
        fill = theme.loss_colour(carried.loss_pct or 0.0)
        details = self._details(hop, carried, dest)
        for point, responder in zip(at, hop.responders):
            circle = self._circle(point, hop.ttl, fill, dest=dest)
            circle.setToolTip(details)
            circles.append(circle)
            name = elide(responder.name or responder.address)
            share = f" ({responder.count}/{s.received})" if len(hop.responders) > 1 else ""
            self._text(name + share, QPointF(point.x(), point.y() + RADIUS + 4),
                       theme.ink, bold=dest, ttl=hop.ttl)
        y = at[-1].y() + RADIUS + 22
        if len(hop.responders) > MAX_SHOWN:
            self._text(f"+{len(hop.responders) - MAX_SHOWN} more", QPointF(at[-1].x(), y),
                       theme.muted, small=True)
            y += 18
        # Grey: that number stops at this hop (see carried_on).
        self._text(f"{fmt_ms(s.avg)} ms", QPointF(at[-1].x(), y),
                   theme.muted if carried.slow_to_reply else theme.secondary, small=True, ttl=hop.ttl)
        self._text(f"{s.loss_pct:.0f}% loss", QPointF(at[-1].x(), y + 15),
                   theme.muted if carried.loss_stops_here else theme.secondary, small=True,
                   ttl=hop.ttl)

    def _details(self, hop: HopSnapshot, carried: Carried, dest: bool) -> str:
        s = hop.stats
        lines = [f"hop {hop.ttl}" + (" (the destination)" if dest else "")]
        lines += [f"{r.name or r.address}" + (f" ({r.address})" if r.name else "") + f": {r.count} answers"
                  for r in hop.responders]
        lines.append(f"sent {s.sent}, loss {s.loss_pct:.1f}%, avg {fmt_ms(s.avg)} ms, "
                     f"best {fmt_ms(s.best)}, worst {fmt_ms(s.worst)}")
        if carried.loss_stops_here:
            lines.append(f"Only {carried.loss_pct:.1f}% loss carries on to the hops after it: the rest "
                         "is this router rate-limiting its replies, not your traffic being dropped.")
        if carried.slow_to_reply:
            lines.append(f"Only {fmt_ms(carried.avg)} ms carries on to the hops after it: this router "
                         "is slow to reply, not slow to forward.")
        return "\n".join(lines)

    def _circle(self, at: QPointF, ttl: int, fill: str | None, *, dest: bool = False,
                dashed: bool = False) -> QGraphicsEllipseItem:
        theme = self.theme
        rect = QRectF(at.x() - RADIUS, at.y() - RADIUS, 2 * RADIUS, 2 * RADIUS)
        if dashed:
            pen = QPen(QColor(theme.muted), 1.5, Qt.PenStyle.DashLine)
        else:
            pen = QPen(QColor(theme.surface), 2)  # a ring of surface keeps it clear of its lines
        brush = QBrush(QColor(fill)) if fill else QBrush(QColor(theme.surface))
        circle = self.scene().addEllipse(rect, pen, brush)
        circle.setData(TTL_KEY, ttl)
        circle.setZValue(3)
        circle.setCursor(Qt.CursorShape.PointingHandCursor)
        if dest or ttl == self.selected:
            outer = rect.adjusted(-5, -5, 5, 5)
            ring = self.scene().addEllipse(outer, QPen(QColor(theme.ink), 3 if ttl == self.selected else 1.5),
                                           QBrush(Qt.BrushStyle.NoBrush))
            ring.setData(TTL_KEY, ttl)
            ring.setZValue(2)
        return circle

    def _text(self, text: str, centre_top: QPointF, colour: str, *, small: bool = False,
              bold: bool = False, ttl: int | None = None) -> QGraphicsSimpleTextItem:
        item = QGraphicsSimpleTextItem(text)
        font = QFont(self._small if small else self.font())
        font.setBold(bold)
        item.setFont(font)
        item.setBrush(QColor(colour))
        width = item.boundingRect().width()
        item.setPos(centre_top.x() - width / 2, centre_top.y())
        item.setZValue(4)
        if ttl is not None:
            item.setData(TTL_KEY, ttl)
        self.scene().addItem(item)
        return item

    def _legend(self, at: QPointF) -> None:
        """What the colours mean, under the diagram: a swatch beside each label."""
        theme = self.theme
        x = at.x()
        entries: list[tuple[QGraphicsItem | None, str]] = []
        for colour, label in ((theme.good, "no loss"), (theme.warning, "under 5% loss"),
                              (theme.critical, "5% or more")):
            entries.append((self.scene().addEllipse(QRectF(0, 0, 10, 10), QPen(Qt.PenStyle.NoPen),
                                                    QBrush(QColor(colour))), label))
        entries.append((None, "(loss that carries on to later hops; grey numbers stop at their hop)"
                              "     edges: latency added on the link,"))
        for step, label in ((1, "1"), (10, "10"), (100, "100 ms")):
            entries.append((self.scene().addRect(QRectF(0, 3, 18, 4), QPen(Qt.PenStyle.NoPen),
                                                 QBrush(QColor(theme.latency_colour(step)))), label))
        for swatch, label in entries:
            if swatch is not None:
                swatch.setPos(x, at.y() + 3)
                x += swatch.boundingRect().width() + 4
            item = self._text(label, QPointF(0, at.y()), theme.muted, small=True)
            item.setPos(x, at.y())
            x += item.boundingRect().width() + 12
