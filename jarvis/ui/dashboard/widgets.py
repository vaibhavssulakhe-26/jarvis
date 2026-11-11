"""Custom widgets: the particle orb, ring gauges, glass panels and the note graph. Painted with QPainter only, no graphics effects."""
import math
import random
import re
import time

from PyQt6.QtCore import QLineF, QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QFrame, QLabel, QVBoxLayout, QWidget

from ...actions import events
from .theme import alpha

FPS = 30
LOW_FPS = 15
POINTS = 120
LOW_POINTS = 40
SPIN = {"idle": 0.12, "listening": 0.3, "thinking": 1.1, "speaking": 0.45}
BRIGHT = {"idle": 0.4, "listening": 0.85, "thinking": 0.75, "speaking": 0.9}


def mono(size=9, bold=False):
    f = QFont()
    f.setFamilies(["JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", "monospace"])
    f.setStyleHint(QFont.StyleHint.Monospace)
    f.setPointSize(size)
    f.setBold(bold)
    return f


class Clock(QObject):
    """The one animation timer: 30 fps, 15 in low power, stopped while the window is hidden."""
    tick = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.low = False
        self.visible = True
        self._t = QTimer(self)
        self._t.timeout.connect(self.tick)
        self._apply()

    def _apply(self):
        if self.visible:
            self._t.start(int(1000 / (LOW_FPS if self.low else FPS)))
        else:
            self._t.stop()

    def set_low(self, low):
        self.low = bool(low)
        self._apply()

    def set_visible(self, visible):
        self.visible = bool(visible)
        self._apply()

    @property
    def running(self):
        return self._t.isActive()

    @property
    def interval(self):
        return self._t.interval()


class Panel(QFrame):
    """A translucent panel with a thin glowing border and a small-caps title."""

    def __init__(self, theme, title="", parent=None):
        super().__init__(parent)
        self.theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, False)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(14, 12, 14, 12)
        self.box.setSpacing(6)
        if title:
            cap = QLabel(title.upper())
            cap.setObjectName("cap")
            self.box.addWidget(cap)
        theme.changed.connect(self.update)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.theme.panel)
        p.drawRoundedRect(r, 8, 8)
        g = self.theme.glow_strength
        p.setBrush(Qt.BrushStyle.NoBrush)
        for width, a in ((4.0, 14), (2.5, 30)):
            p.setPen(QPen(alpha(self.theme.accent, a * g), width))
            p.drawRoundedRect(r, 8, 8)
        p.setPen(QPen(alpha(self.theme.accent, 150 * g), 1))
        p.drawRoundedRect(r, 8, 8)
        tick = alpha(self.theme.accent, 220)
        p.setPen(QPen(tick, 2))
        x0, y0, x1, y1 = r.left(), r.top(), r.right(), r.bottom()
        for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
            p.drawLine(QLineF(x, y, x + 10 * dx, y))
            p.drawLine(QLineF(x, y, x, y + 10 * dy))


class RingGauge(QWidget):
    def __init__(self, theme, label, parent=None):
        super().__init__(parent)
        self.theme, self.label, self.value = theme, label, 0.0
        self.setMinimumSize(80, 86)
        theme.changed.connect(self.update)

    def set_value(self, value):
        self.value = max(0.0, min(100.0, float(value)))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height() - 16) - 10
        r = QRectF((self.width() - side) / 2, 4, side, side)
        p.setPen(QPen(alpha(self.theme.accent, 40), 5))
        p.drawArc(r, 0, 360 * 16)
        colour = self.theme.bad if self.value > 90 else self.theme.warn if self.value > 75 else self.theme.accent
        p.setPen(QPen(colour, 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, int(-self.value * 3.6 * 16))
        p.setPen(self.theme.text)
        p.setFont(mono(10, True))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{self.value:.0f}")
        p.setPen(self.theme.dim)
        p.setFont(mono(7))
        p.drawText(QRectF(0, self.height() - 14, self.width(), 14), Qt.AlignmentFlag.AlignCenter, self.label)


def fibonacci_sphere(n):
    pts = []
    golden = math.pi * (3 - math.sqrt(5))
    for i in range(n):
        y = 1 - (i / max(1, n - 1)) * 2
        r = math.sqrt(max(0.0, 1 - y * y))
        t = golden * i
        pts.append((math.cos(t) * r, y, math.sin(t) * r))
    return pts


def neighbours(pts, per=3):
    pairs = set()
    for i, a in enumerate(pts):
        near = sorted(range(len(pts)), key=lambda j: (a[0] - pts[j][0]) ** 2 + (a[1] - pts[j][1]) ** 2 + (a[2] - pts[j][2]) ** 2)[1:per + 1]
        pairs.update((min(i, j), max(i, j)) for j in near)
    return sorted(pairs)


class Orb(QWidget):
    """About 120 points joined by faint lines, turning slowly in 3D, with rings behind and ripples when it speaks."""

    def __init__(self, theme, clock, parent=None):
        super().__init__(parent)
        self.theme, self.clock = theme, clock
        self.mode = "idle"
        self.angle = random.random() * 6.28
        self.mic = 0.0
        self.voice = 0.0
        self.ripples = []
        self.last_ripple = 0.0
        self.last = time.monotonic()
        self.low = False
        self.sets = {}
        self.setMinimumSize(280, 280)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self._build(POINTS)
        clock.tick.connect(self.advance)

    def _build(self, n):
        if n not in self.sets:
            pts = fibonacci_sphere(n)
            self.sets[n] = (pts, neighbours(pts))
        self.pts, self.pairs = self.sets[n]

    @property
    def count(self):
        return len(self.pts)

    def set_low(self, low):
        self.low = bool(low)
        self._build(LOW_POINTS if low else POINTS)
        if low:
            self.ripples.clear()

    def set_mode(self, mode):
        self.mode = mode if mode in SPIN else "idle"

    def advance(self):
        now = time.monotonic()
        dt = min(0.2, now - self.last)
        self.last = now
        self.angle += SPIN[self.mode] * dt
        self.mic += (min(1.0, events.level * 6) - self.mic) * min(1.0, dt * 8)
        self.voice += (min(1.0, events.out_level) - self.voice) * min(1.0, dt * 10)
        if self.mode == "speaking" and not self.low and self.voice > 0.15 and now - self.last_ripple > 0.4:
            self.last_ripple = now
            self.ripples.append(now)
        self.ripples = [t for t in self.ripples if now - t < 1.6]
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        base = min(w, h) * 0.30
        t = self.theme
        p.fillRect(self.rect(), t.bg)
        bright = BRIGHT[self.mode]
        g = t.glow_strength
        if not self.low:
            for k, (scale, dash) in enumerate(((1.45, 8), (1.75, 3))):
                pen = QPen(alpha(t.accent, (38 - k * 14) * g), 1)
                pen.setStyle(Qt.PenStyle.DashLine if k == 0 else Qt.PenStyle.DotLine)
                p.setPen(pen)
                p.drawEllipse(QPointF(cx, cy), base * scale, base * scale)
            arc = QPen(alpha(t.secondary, 120 * g), 2)
            p.setPen(arc)
            r = QRectF(cx - base * 1.45, cy - base * 1.45, base * 2.9, base * 2.9)
            p.drawArc(r, int(-self.angle * 900) % (360 * 16), 70 * 16)
            p.drawArc(r, int(-self.angle * 900 + 180 * 16) % (360 * 16), 40 * 16)
        now = time.monotonic()
        for born in self.ripples:
            age = (now - born) / 1.6
            p.setPen(QPen(alpha(t.accent, 140 * (1 - age) * g), 2))
            rad = base * (1.0 + age * 0.9)
            p.drawEllipse(QPointF(cx, cy), rad, rad)
        spread = 1.0
        if self.mode == "listening":
            spread += 0.35 * self.mic
        elif self.mode == "speaking":
            spread += 0.25 * self.voice
        radius = base * spread
        ca, sa = math.cos(self.angle), math.sin(self.angle)
        tilt = 0.35
        ct, st = math.cos(tilt), math.sin(tilt)
        proj = []
        for x, y, z in self.pts:
            x, z = x * ca + z * sa, -x * sa + z * ca
            y, z = y * ct - z * st, y * st + z * ct
            persp = 1.0 / (1.0 - z * 0.28)
            proj.append((cx + x * radius * persp, cy + y * radius * persp, z))
        front, back = [], []
        for i, j in self.pairs:
            a, b = proj[i], proj[j]
            (front if a[2] + b[2] > 0 else back).append(QLineF(a[0], a[1], b[0], b[1]))
        p.setPen(QPen(alpha(t.accent, 45 * bright), 1))
        p.drawLines(back)
        p.setPen(QPen(alpha(t.accent, 120 * bright), 1))
        p.drawLines(front)
        size = 22 if not self.low else 26
        sprite = t.glow(32, 1.0)
        p.setOpacity(min(1.0, bright))
        for x, y, z in proj:
            s = size * (0.6 + 0.4 * (z + 1) / 2) * (0.7 + 0.3 * g)
            p.drawPixmap(QRectF(x - s / 2, y - s / 2, s, s), sprite, QRectF(sprite.rect()))
        p.setOpacity(1.0)
        core = t.glow(64, 1.0)
        c = base * 0.9 * (0.8 + 0.4 * bright)
        p.setOpacity(0.25 + 0.3 * bright)
        p.drawPixmap(QRectF(cx - c, cy - c, c * 2, c * 2), core, QRectF(core.rect()))


STOPWORDS = {"the", "and", "for", "that", "this", "with", "have", "from", "are", "was", "were", "you", "your", "not", "but", "can", "will",
             "all", "has", "had", "its", "our", "out", "into", "about", "what", "when", "which", "their", "they", "them", "then", "than"}


def keywords(text, n=8):
    counts = {}
    for w in re.findall(r"[a-z]{4,}", text.lower()):
        if w not in STOPWORDS:
            counts[w] = counts.get(w, 0) + 1
    return [w for w, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


class MemoryGraph(QWidget):
    """Notes as nodes, joined when they share keywords. Click a node to open it; the search term lights up matches."""
    opened = pyqtSignal(str)

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.theme = theme
        self.nodes = []
        self.edges = []
        self.match = set()
        self.selected = None
        self.setMinimumSize(320, 260)
        theme.changed.connect(self.update)

    def load(self, notes, limit=60):
        """notes: list of (name, text). Builds the keyword links and a settled layout."""
        notes = notes[:limit]
        self.nodes = [dict(name=n, words=set(keywords(t)), text=t.lower(), x=0.0, y=0.0) for n, t in notes]
        self.edges = [(i, j) for i in range(len(self.nodes)) for j in range(i + 1, len(self.nodes))
                      if len(self.nodes[i]["words"] & self.nodes[j]["words"]) >= 2]
        rng = random.Random(7)
        for k, n in enumerate(self.nodes):
            ang = k / max(1, len(self.nodes)) * 6.283
            n["x"], n["y"] = math.cos(ang) * 0.5 + rng.uniform(-.05, .05), math.sin(ang) * 0.5 + rng.uniform(-.05, .05)
        for _ in range(80):
            for a in self.nodes:
                fx = fy = 0.0
                for b in self.nodes:
                    if a is b:
                        continue
                    dx, dy = a["x"] - b["x"], a["y"] - b["y"]
                    d2 = dx * dx + dy * dy + 0.01
                    fx += dx / d2 * 0.002
                    fy += dy / d2 * 0.002
                a["x"] += fx - a["x"] * 0.02
                a["y"] += fy - a["y"] * 0.02
            for i, j in self.edges:
                a, b = self.nodes[i], self.nodes[j]
                dx, dy = b["x"] - a["x"], b["y"] - a["y"]
                a["x"] += dx * 0.03
                a["y"] += dy * 0.03
                b["x"] -= dx * 0.03
                b["y"] -= dy * 0.03
        self.update()

    def highlight(self, query):
        words = [w for w in re.findall(r"[a-z0-9]+", str(query).lower()) if len(w) > 1]
        self.match = {i for i, n in enumerate(self.nodes) if words and all(w in n["text"] or w in n["name"].lower() for w in words)}
        self.update()

    def _pos(self, n):
        xs = [m["x"] for m in self.nodes] or [0]
        ys = [m["y"] for m in self.nodes] or [0]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 0.1)
        s = (min(self.width(), self.height()) - 50) / span
        return (self.width() / 2 + (n["x"] - (max(xs) + min(xs)) / 2) * s, self.height() / 2 + (n["y"] - (max(ys) + min(ys)) / 2) * s)

    def mousePressEvent(self, ev):
        for i, n in enumerate(self.nodes):
            x, y = self._pos(n)
            if (ev.position().x() - x) ** 2 + (ev.position().y() - y) ** 2 < 100:
                self.selected = i
                self.update()
                self.opened.emit(n["name"])
                return

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        t = self.theme
        if not self.nodes:
            p.setPen(t.dim)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "no notes yet")
            return
        pos = [self._pos(n) for n in self.nodes]
        p.setPen(QPen(alpha(t.accent, 55), 1))
        for i, j in self.edges:
            p.drawLine(QPointF(*pos[i]), QPointF(*pos[j]))
        sprite = t.glow(32, 1.0)
        for i, (x, y) in enumerate(pos):
            hot = i in self.match
            s = 34 if hot else 20
            p.setOpacity(1.0 if hot or i == self.selected else 0.7)
            p.drawPixmap(QRectF(x - s / 2, y - s / 2, s, s), sprite, QRectF(sprite.rect()))
            p.setOpacity(1.0)
            p.setBrush(t.warn if hot else t.accent)
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 3.5, 3.5)
            if hot or i == self.selected or len(self.nodes) <= 14:
                p.setPen(t.text if hot or i == self.selected else t.dim)
                p.setFont(mono(8))
                p.drawText(QPointF(x + 7, y - 6), self.nodes[i]["name"][:22])
