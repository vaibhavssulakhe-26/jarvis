"""The star field and the globe. Painted with QPainter only: pre-rendered star layers, about 300 live particles, and a Fibonacci point cloud
projected by hand. The look of each of the six states is a plain table (LOOKS) so the mapping can be tested without drawing."""
import math
import random
from dataclasses import dataclass

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF, QRadialGradient

from . import design

LAYERS = ((1500, 0.6, 0.18), (1100, 0.8, 0.30), (700, 1.1, 0.45))
PARALLAX = (4.0, 9.0, 16.0)
MARGIN = 24
REPEL_RADIUS = 130.0
GLOBE_FRACTION = 0.34
TILT = 0.38
EASE = 0.12


@dataclass(frozen=True)
class Look:
    """How one state draws the globe. spin is turns per minute, bright 0 to 1, pulse where the size rhythm comes from, rings expanding around it."""
    spin: float
    bright: float
    tint: str
    pulse: str
    rings: int
    atmosphere: float


LOOKS = {
    "idle": Look(4.0, 0.60, design.ACCENT, "none", 0, 0.45),
    "listening": Look(7.0, 0.92, "#9fb4ff", "mic", 0, 0.75),
    "thinking": Look(26.0, 0.85, "#b9a2ff", "none", 3, 0.65),
    "speaking": Look(10.0, 1.00, "#a5c8ff", "voice", 0, 0.85),
    "error": Look(1.5, 0.90, design.ERROR, "none", 0, 0.70),
    "offline": Look(0.0, 0.26, design.OFFLINE, "none", 0, 0.12),
}


def look_for(name):
    return LOOKS.get(name, LOOKS["idle"])


def fibonacci(n):
    """n points spread evenly over a unit sphere, as an (n, 3) array."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * i / n)
    theta = math.pi * (1 + 5 ** 0.5) * i
    return np.stack([np.cos(theta) * np.sin(phi), np.cos(phi), np.sin(theta) * np.sin(phi)], axis=1)


def _mix(a, b, f):
    return QColor(int(a.red() + (b.red() - a.red()) * f), int(a.green() + (b.green() - a.green()) * f), int(a.blue() + (b.blue() - a.blue()) * f))


class StarField:
    """Three pre-rendered layers of dots (parallax) and live particles that drift and ease away from the cursor."""

    def __init__(self, seed=7):
        self.rng = random.Random(seed)
        self.size = (0, 0)
        self.layers = []
        self.count = 0
        self.pos = np.zeros((0, 2))
        self.vel = np.zeros((0, 2))
        self.depth = np.zeros(0)
        self.np_rng = np.random.default_rng(seed)

    def resize(self, w, h):
        if (w, h) == self.size:
            return
        self.size = (w, h)
        self.layers = [self._render(w, h, n, r, a) for n, r, a in LAYERS]
        self._seed_particles(self.count)

    def _render(self, w, h, n, radius, alpha):
        pm = QPixmap(w + 2 * MARGIN, h + 2 * MARGIN)
        pm.fill(Qt.GlobalColor.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        for _ in range(n):
            c = QColor("#dfe6ff" if self.rng.random() > 0.2 else "#b9c4ff")
            c.setAlphaF(alpha * (0.4 + 0.6 * self.rng.random()))
            p.setBrush(c)
            r = radius * (0.6 + 0.8 * self.rng.random())
            p.drawEllipse(QPointF(self.rng.random() * pm.width(), self.rng.random() * pm.height()), r, r)
        p.end()
        return pm

    def set_count(self, n):
        if n != self.count:
            self.count = n
            self._seed_particles(n)

    def _seed_particles(self, n):
        w, h = max(1, self.size[0]), max(1, self.size[1])
        self.pos = self.np_rng.random((n, 2)) * [w, h]
        self.vel = (self.np_rng.random((n, 2)) - 0.5) * 6
        self.depth = 0.4 + self.np_rng.random(n) * 0.6

    def step(self, dt, cursor, drift=True):
        """Advance the particles. `cursor` is in pixels or None. Positions wrap around the edges."""
        if not self.count or not drift:
            return
        w, h = self.size
        self.vel += (self.np_rng.random(self.vel.shape) - 0.5) * 6 * dt
        if cursor is not None:
            d = self.pos - np.array(cursor)
            dist = np.sqrt((d ** 2).sum(axis=1)) + 1e-3
            near = dist < REPEL_RADIUS
            push = np.where(near, (1 - dist / REPEL_RADIUS) ** 2 * 260, 0.0)
            self.vel += d / dist[:, None] * push[:, None] * dt
        self.vel *= max(0.0, 1 - 1.6 * dt)
        speed = np.sqrt((self.vel ** 2).sum(axis=1))
        slow = speed < 4
        self.vel[slow] += (self.np_rng.random((int(slow.sum()), 2)) - 0.5) * 5 * dt
        self.pos += self.vel * dt * self.depth[:, None]
        self.pos[:, 0] %= max(1, w)
        self.pos[:, 1] %= max(1, h)

    def paint(self, p, cursor_unit, parallax=True, offset_y=0.0):
        """cursor_unit is the cursor as -1..1 on both axes. offset_y shifts the layers a little while the screen scrolls."""
        cx, cy = cursor_unit if parallax else (0.0, 0.0)
        for pm, depth in zip(self.layers, PARALLAX):
            p.drawPixmap(int(-MARGIN - cx * depth), int(-MARGIN - cy * depth + offset_y * depth / 16), pm)
        if self.count:
            p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            for lo, hi, a, size in ((0.0, 0.7, 120, 1.6), (0.7, 1.01, 200, 2.2)):
                mask = (self.depth >= lo) & (self.depth < hi)
                if not mask.any():
                    continue
                c = QColor("#cdd6ff")
                c.setAlpha(a)
                p.setPen(QPen(c, size, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
                pts = self.pos[mask]
                shift = np.array([cx, cy]) * 10 * (lo + 0.3)
                p.drawPoints(QPolygonF([QPointF(x - shift[0], y - shift[1] + offset_y * 0.2) for x, y in pts]))
            p.setRenderHint(QPainter.RenderHint.Antialiasing, True)


class Globe:
    """The one dominant globe. It eases between looks, tilts toward the cursor and takes its pulse from the mic or the voice."""

    def __init__(self, points=1100):
        self.set_points(points)
        self.name = "idle"
        self.angle = 0.0
        self.spin = look_for("idle").spin
        self.bright = look_for("idle").bright
        self.atmos = look_for("idle").atmosphere
        self.tint = QColor(look_for("idle").tint)
        self.tilt = [0.0, 0.0]
        self.pulse = 0.0
        self.ring_phase = 0.0
        self.peak = 0.05
        self._atmo_cache = {}

    def set_points(self, n):
        self.n = n
        self.cloud = fibonacci(n)

    def set_state(self, name):
        self.name = name

    def level(self, mic, voice):
        """The 0 to 1 rhythm for this state. The mic is normalised against a decaying peak so a quiet room still moves it."""
        look = look_for(self.name)
        if look.pulse == "mic":
            self.peak = max(self.peak * 0.995, float(mic), 0.02)
            return min(1.0, float(mic) / self.peak)
        if look.pulse == "voice":
            return min(1.0, float(voice))
        return 0.0

    def step(self, dt, cursor_unit, mic=0.0, voice=0.0, speed=1.0):
        look = look_for(self.name)
        k = 1 - (1 - EASE) ** (dt * 30)
        self.spin += (look.spin - self.spin) * k
        self.bright += (look.bright - self.bright) * k
        self.atmos += (look.atmosphere - self.atmos) * k
        self.tint = _mix(self.tint, QColor(look.tint), k)
        self.angle = (self.angle + self.spin * speed * dt * math.tau / 60.0) % math.tau
        self.tilt[0] += (cursor_unit[0] * TILT - self.tilt[0]) * k
        self.tilt[1] += (cursor_unit[1] * TILT - self.tilt[1]) * k
        self.pulse += (self.level(mic, voice) - self.pulse) * min(1.0, k * 2.2)
        self.ring_phase = (self.ring_phase + dt * 0.55) % 1.0

    def project(self, centre, radius):
        """(screen x, screen y, depth) arrays for every point, after the spin and the cursor tilt."""
        pts = self.cloud
        c, s = math.cos(self.angle), math.sin(self.angle)
        x = pts[:, 0] * c + pts[:, 2] * s
        z = -pts[:, 0] * s + pts[:, 2] * c
        y = pts[:, 1]
        cx, sx = math.cos(self.tilt[1] * 0.8 + 0.25), math.sin(self.tilt[1] * 0.8 + 0.25)
        y, z = y * cx - z * sx, y * sx + z * cx
        cy, sy = math.cos(self.tilt[0]), math.sin(self.tilt[0])
        x, z = x * cy + z * sy, -x * sy + z * cy
        scale = radius * (1 + 0.05 * self.pulse)
        return centre.x() + x * scale, centre.y() - y * scale, z

    def atmosphere(self, radius):
        """A soft glow ring, rendered once per size and tint step."""
        step = tuple(int(v // 24) for v in (self.tint.red(), self.tint.green(), self.tint.blue()))
        key = (int(radius), step)
        if key not in self._atmo_cache:
            if len(self._atmo_cache) > 12:
                self._atmo_cache.clear()
            size = int(radius * 2.9)
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            g = QRadialGradient(QPointF(size / 2, size / 2), size / 2)
            tint = QColor(*(min(255, v * 24 + 12) for v in step))
            for stop, a in ((0.0, 0.0), (0.58, 0.0), (0.66, 0.30), (0.78, 0.09), (1.0, 0.0)):
                c = QColor(tint)
                c.setAlphaF(a)
                g.setColorAt(stop, c)
            p.fillRect(pm.rect(), g)
            p.end()
            self._atmo_cache[key] = pm
        return self._atmo_cache[key]

    def paint(self, p, rect):
        centre = rect.center()
        radius = min(rect.width(), rect.height()) * GLOBE_FRACTION
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        r_pulse = radius * (1 + 0.05 * self.pulse)
        pm = self.atmosphere(r_pulse)
        p.setOpacity(max(0.0, min(1.0, self.atmos + 0.25 * self.pulse)))
        p.drawPixmap(int(centre.x() - pm.width() / 2), int(centre.y() - pm.height() / 2), pm)
        p.setOpacity(1.0)
        look = look_for(self.name)
        if look.rings:
            for i in range(look.rings):
                f = (self.ring_phase + i / look.rings) % 1.0
                c = QColor(self.tint)
                c.setAlphaF(0.5 * (1 - f))
                p.setPen(QPen(c, 1.2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                rr = r_pulse * (1.02 + 0.38 * f)
                p.drawEllipse(centre, rr, rr)
        x, y, z = self.project(centre, radius)
        lit, edge = QColor(self.tint), QColor(self.tint)
        lit.setAlphaF(0.20 * self.bright)
        edge.setAlphaF(0.04)
        shade = QRadialGradient(QPointF(centre.x() - r_pulse * 0.3, centre.y() - r_pulse * 0.35), r_pulse * 1.35)
        shade.setColorAt(0, lit)
        shade.setColorAt(1, edge)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(shade)
        p.drawEllipse(centre, r_pulse * 0.985, r_pulse * 0.985)
        # four depth buckets, far to near; each is one drawPoints call
        edges = (-1.01, -0.1, 0.25, 0.6, 1.01)
        for i in range(4):
            mask = (z >= edges[i]) & (z < edges[i + 1])
            if not mask.any():
                continue
            near = (i + 1) / 4
            c = QColor("#ffffff")
            c = _mix(self.tint, c, 0.5 * near)
            c.setAlphaF(min(1.0, (0.16 + 0.84 * near ** 1.2) * self.bright))
            p.setPen(QPen(c, 1.6 + 2.6 * near, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            p.drawPoints(QPolygonF([QPointF(a, b) for a, b in zip(x[mask], y[mask])]))
        p.setBrush(Qt.BrushStyle.NoBrush)
        return QRectF(centre.x() - r_pulse, centre.y() - r_pulse, 2 * r_pulse, 2 * r_pulse)
