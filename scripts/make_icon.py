"""Draws the app icon: a small scanline globe in teal and amber."""
import math
import os
import sys
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QGuiApplication, QPainter, QPen, QPixmap, QRadialGradient

OUT = Path(__file__).resolve().parent.parent / "assets" / "ana.png"


def main():
    app = QGuiApplication(sys.argv)
    size = 256
    pm = QPixmap(size, size)
    pm.fill(QColor(7, 9, 11))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    c = size / 2
    g = QRadialGradient(QPointF(c, c * 1.5), size * 0.8)
    g.setColorAt(0.0, QColor(110, 52, 14))
    g.setColorAt(1.0, QColor(7, 9, 11))
    p.fillRect(pm.rect(), QBrush(g))
    R = size * 0.30
    rows = int(R * 2 / 4)
    for i in range(rows):
        fy = (i + 0.5) / rows
        dy = (fy - 0.5) * 2
        half = R * math.sqrt(max(0.0, 1 - dy * dy))
        col = QColor(46 + int(209 * fy), 230 - int(76 * fy), 214 - int(183 * fy))
        col.setAlpha(230 if i % 2 == 0 else 120)
        p.setPen(QPen(col, 2))
        y = c - R + fy * 2 * R
        p.drawLine(QPointF(c - half, y), QPointF(c + half, y))
    p.setPen(QPen(QColor(255, 154, 31, 170), 2))
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawEllipse(QPointF(c, c), R * 1.35, R * 0.42)
    p.end()
    OUT.parent.mkdir(exist_ok=True)
    pm.save(str(OUT))
    print("icon saved")


if __name__ == "__main__":
    main()
