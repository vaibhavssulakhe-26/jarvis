"""The seven floating bubbles: spring physics that never lets two of them overlap (World, no Qt), and the focusable widgets that draw them."""
import math
import random

from PyQt6.QtCore import QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetrics, QPainter, QPen, QPixmap, QRadialGradient, QRegion
from PyQt6.QtWidgets import QAbstractButton

from . import design
from .dashboard import icons

NAMES = ("Settings", "Notes", "Home", "Chat", "Web Search", "Media", "Stats")
ICONS = {"Web Search": "Web"}
GROW = 0.12
GAP = 8.0
DRIFT = 11.0
MAX_R = 76.0
MIN_R = 26.0
SPRING = 16.0
DAMP = 5.5
BOTTOM_RESERVE = 96


class Body:
    def __init__(self, key, rng):
        self.key = key
        self.x = self.y = self.vx = self.vy = 0.0
        self.ax = self.ay = 0.0
        self.px, self.py = rng.random() * math.tau, rng.random() * math.tau
        self.fx, self.fy = 0.25 + rng.random() * 0.25, 0.2 + rng.random() * 0.25


class World:
    """Bubbles tied to drifting anchors by springs. After every step a projection pass separates any pair closer than their collision radii and
    keeps each inside the area, so the no-overlap guarantee does not depend on how stiff the springs are."""

    def __init__(self, keys=NAMES, seed=3):
        self.rng = random.Random(seed)
        self.bodies = [Body(k, self.rng) for k in keys]
        self.w = self.h = 0
        self.r = MIN_R
        self.rc = MIN_R
        self.t = 0.0
        self.placed = False

    def layout(self, w, h):
        """Size the bubbles for the area and put the anchors on a grid of rows, the last row centred."""
        self.w, self.h = w, h
        n = len(self.bodies)
        cols = 4 if w >= 860 and h >= 440 else 3
        rows = math.ceil(n / cols)
        usable_h = max(1.0, h - BOTTOM_RESERVE)
        cell_w, cell_h = w / cols, usable_h / rows
        self.r = max(MIN_R, min(MAX_R, ((min(cell_w, cell_h) / 2) - DRIFT - GAP) / (1 + GROW)))
        self.rc = self.r * (1 + GROW) + GAP
        i = 0
        for row in range(rows):
            count = min(cols, n - i)
            for c in range(count):
                b = self.bodies[i]
                b.ax = w / 2 + (c - (count - 1) / 2) * cell_w
                b.ay = usable_h * (row + 0.5) / rows
                i += 1
        if not self.placed:
            for b in self.bodies:
                b.x, b.y = b.ax, b.ay
            self.placed = True
        self.settle()

    @property
    def collision(self):
        """The smallest distance two centres may have: both bubbles fully grown plus the gap."""
        return 2 * self.rc

    def step(self, dt, drift=True):
        dt = min(dt, 1 / 20)
        if not self.w:
            return
        self.t += dt
        amp = DRIFT if drift else 0.0
        for b in self.bodies:
            tx = b.ax + amp * math.sin(self.t * b.fx * math.tau + b.px)
            ty = b.ay + amp * math.cos(self.t * b.fy * math.tau + b.py)
            b.vx += (SPRING * (tx - b.x) - DAMP * b.vx) * dt
            b.vy += (SPRING * (ty - b.y) - DAMP * b.vy) * dt
            b.x += b.vx * dt
            b.y += b.vy * dt
        self.settle()

    def settle(self):
        """Walls, then pairs, until nothing moves (one or two passes in normal use). Two bubbles that start inside each other are pushed apart along their line (or an arbitrary one)."""
        rc = self.rc
        lo_x, hi_x = rc, max(rc, self.w - rc)
        lo_y, hi_y = rc, max(rc, self.h - BOTTOM_RESERVE - rc)
        for _ in range(300):
            for b in self.bodies:
                b.x = min(max(b.x, lo_x), hi_x)
                b.y = min(max(b.y, lo_y), hi_y)
            moved = False
            for i, a in enumerate(self.bodies):
                for c in self.bodies[i + 1:]:
                    dx, dy = c.x - a.x, c.y - a.y
                    d = math.hypot(dx, dy)
                    need = 2 * rc
                    if d < need - 1e-6:
                        if d < 1e-6:
                            dx, dy, d = 1.0, 0.0, 1.0
                        push = (need - d) / 2 + 0.01
                        ux, uy = dx / d, dy / d
                        a.x -= ux * push
                        a.y -= uy * push
                        c.x += ux * push
                        c.y += uy * push
                        moved = True
            if not moved:
                break
        for b in self.bodies:
            b.x = min(max(b.x, lo_x), hi_x)
            b.y = min(max(b.y, lo_y), hi_y)


_glass = {}


def _bubble_pixmap(diameter, hot):
    key = (diameter, hot)
    if key not in _glass:
        if len(_glass) > 40:
            _glass.clear()
        pm = QPixmap(diameter, diameter)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = diameter / 2
        g = QRadialGradient(QPointF(c, c * 0.8), c * 1.1)
        inner, outer = QColor("#2a2f5c" if hot else "#1c2040"), QColor(design.PANEL)
        inner.setAlpha(235)
        outer.setAlpha(240)
        g.setColorAt(0, inner)
        g.setColorAt(1, outer)
        p.setBrush(g)
        edge = QColor(design.ACCENT if hot else "#ffffff")
        edge.setAlpha(150 if hot else 36)
        p.setPen(QPen(edge, 1))
        p.drawEllipse(QRectF(0.5, 0.5, diameter - 1, diameter - 1))
        p.end()
        _glass[key] = pm
    return _glass[key]


class Bubble(QAbstractButton):
    """One floating bubble. Hover and focus grow and brighten it; the label sits inside the circle so it can never touch a neighbour."""
    navigate = pyqtSignal(object, str)

    def __init__(self, name, parent=None):
        super().__init__(parent)
        self.name = name
        self.r = MIN_R
        self.rc = MIN_R
        self.glow = 0.0
        self.hover = False
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAccessibleName(name)
        self.setToolTip(name)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self._icon = {}

    def fit(self, r, rc):
        self.r, self.rc = r, rc
        d = int(math.ceil(2 * rc))
        self.resize(d, d)
        self.setMask(QRegion(QRect(0, 0, d, d), QRegion.RegionType.Ellipse))

    def sizeHint(self):
        d = int(2 * self.rc)
        return QSize(d, d)

    def hitButton(self, pos):
        c = self.rect().center()
        return math.hypot(pos.x() - c.x(), pos.y() - c.y()) <= self.r * (1 + GROW)

    def enterEvent(self, ev):
        self.hover = True
        super().enterEvent(ev)

    def leaveEvent(self, ev):
        self.hover = False
        super().leaveEvent(ev)

    def lit(self):
        return self.hover or self.hasFocus()

    def ease(self, dt, instant=False):
        target = 1.0 if self.lit() else 0.0
        self.glow = target if instant else self.glow + (target - self.glow) * min(1.0, dt * 14)
        return self.glow

    def label_lines(self):
        fm = QFontMetrics(self._font())
        if fm.horizontalAdvance(self.name) <= self.r * 1.5 or " " not in self.name:
            return [self.name]
        first, rest = self.name.split(" ", 1)
        return [first, rest]

    def _font(self):
        return design.font(int(max(11, min(15, self.r * 0.2))), design.QFont.Weight.Normal)

    def label_rect(self):
        """The label's rectangle at rest size, in widget coordinates. The checks use it to prove it stays inside the circle."""
        fm = QFontMetrics(self._font())
        lines = self.label_lines()
        w = max(fm.horizontalAdvance(t) for t in lines)
        h = fm.height() * len(lines)
        cx, cy = self.width() / 2, self.height() / 2
        return QRectF(cx - w / 2, cy + self.r * 0.22, w, h)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        s = 1 + GROW * self.glow
        c = QPointF(self.width() / 2, self.height() / 2)
        d = int(2 * self.r)
        p.translate(c)
        p.scale(s, s)
        p.drawPixmap(int(-self.r), int(-self.r), _bubble_pixmap(d, False))
        if self.glow > 0.02:
            p.setOpacity(self.glow)
            p.drawPixmap(int(-self.r), int(-self.r), _bubble_pixmap(d, True))
            p.setOpacity(1.0)
        p.resetTransform()
        colour = QColor(design.ACCENT if self.lit() else design.TEXT)
        isz = int(self.r * 0.5)
        key = (isz, colour.name())
        if key not in self._icon:
            self._icon = {key: icons.make(ICONS.get(self.name, self.name), colour).pixmap(isz, isz)}
        p.drawPixmap(int(c.x() - isz / 2), int(c.y() - self.r * 0.55), self._icon[key])
        p.setFont(self._font())
        p.setPen(QColor(design.TEXT))
        fm = QFontMetrics(self._font())
        lines = self.label_lines()
        y = c.y() + self.r * 0.22
        for line in lines:
            p.drawText(QRectF(0, y, self.width(), fm.height()), Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop, line)
            y += fm.height()
        if self.hasFocus():
            ring = QColor(design.ACCENT)
            p.setPen(QPen(ring, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            rr = self.r * s + 3
            p.drawEllipse(c, rr, rr)

    def keyPressEvent(self, ev):
        names = {Qt.Key.Key_Left: "left", Qt.Key.Key_Right: "right", Qt.Key.Key_Up: "up", Qt.Key.Key_Down: "down"}
        if ev.key() in names:
            self.navigate.emit(self, names[ev.key()])
            ev.accept()
        elif ev.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.click()
            ev.accept()
        else:
            super().keyPressEvent(ev)


def neighbour(bubbles, current, direction):
    """The bubble to move focus to for an arrow key: the nearest one that lies in that direction, off-axis distance counting double."""
    cx, cy = current.geometry().center().x(), current.geometry().center().y()
    best, best_score = None, None
    for b in bubbles:
        if b is current or not b.isVisible():
            continue
        dx, dy = b.geometry().center().x() - cx, b.geometry().center().y() - cy
        along, across = {"right": (dx, dy), "left": (-dx, dy), "down": (dy, dx), "up": (-dy, dx)}[direction]
        if along <= 4:
            continue
        score = along + 2 * abs(across)
        if best_score is None or score < best_score:
            best, best_score = b, score
    return best
