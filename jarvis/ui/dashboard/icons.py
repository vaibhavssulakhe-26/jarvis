"""Simple line icons for the sidebar, drawn with QPainter in the current accent colour."""
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QIcon, QPainter, QPen, QPixmap, QPolygonF

SIZE = 20


def _draw(name, p):
    r = QRectF(3, 3, SIZE - 6, SIZE - 6)
    if name == "Home":
        p.drawPolyline(QPolygonF([QPointF(3, 10), QPointF(10, 3.5), QPointF(17, 10)]))
        p.drawPolyline(QPolygonF([QPointF(5, 9), QPointF(5, 16.5), QPointF(15, 16.5), QPointF(15, 9)]))
    elif name == "Media":
        p.drawEllipse(r)
        p.drawPolygon(QPolygonF([QPointF(8.5, 7), QPointF(8.5, 13), QPointF(13.5, 10)]))
    elif name == "Code":
        p.drawPolyline(QPolygonF([QPointF(7, 5.5), QPointF(2.5, 10), QPointF(7, 14.5)]))
        p.drawPolyline(QPolygonF([QPointF(13, 5.5), QPointF(17.5, 10), QPointF(13, 14.5)]))
        p.drawLine(QPointF(11.2, 4.5), QPointF(8.8, 15.5))
    elif name == "Notes":
        p.drawRoundedRect(QRectF(4.5, 2.5, 11, 15), 1.5, 1.5)
        for y in (7, 10, 13):
            p.drawLine(QPointF(7, y), QPointF(13, y))
    elif name == "Study":
        p.drawPolygon(QPolygonF([QPointF(10, 4), QPointF(18, 8), QPointF(10, 12), QPointF(2, 8)]))
        p.drawPolyline(QPolygonF([QPointF(5, 10.5), QPointF(5, 14), QPointF(10, 16.5), QPointF(15, 14), QPointF(15, 10.5)]))
    elif name == "Jobs":
        p.drawRoundedRect(QRectF(2.5, 6.5, 15, 10), 1.5, 1.5)
        p.drawPolyline(QPolygonF([QPointF(7, 6.5), QPointF(7, 4), QPointF(13, 4), QPointF(13, 6.5)]))
        p.drawLine(QPointF(2.5, 11), QPointF(17.5, 11))
    elif name == "Web":
        p.drawEllipse(r)
        p.drawEllipse(QRectF(7, 3, 6, 14))
        p.drawLine(QPointF(3, 10), QPointF(17, 10))
    elif name == "Stats":
        for x, h in ((4.5, 6), (9, 11), (13.5, 8)):
            p.drawRect(QRectF(x, 16 - h, 3, h))
    else:
        for y, x in ((6, 7), (10, 13), (14, 9)):
            p.drawLine(QPointF(3, y), QPointF(17, y))
            p.drawEllipse(QPointF(x, y), 1.8, 1.8)


def make(name, colour):
    """A QIcon for a page name, drawn in the given colour."""
    pm = QPixmap(SIZE * 2, SIZE * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(colour, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
    p.setBrush(Qt.BrushStyle.NoBrush)
    _draw(name, p)
    p.end()
    return QIcon(pm)
