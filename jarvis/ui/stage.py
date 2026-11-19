"""The globe screen: the star field and the globe behind, the seven bubbles one scroll below. One widget, one paint per frame."""
import math
import time
from collections import deque

from PyQt6.QtCore import QEvent, QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QWidget

from ..actions import events
from . import design, status
from .bubbles import BOTTOM_RESERVE, NAMES, Bubble, World, neighbour
from .globe import Globe, StarField

WHEEL_COOLDOWN = 0.45
IDLE_SECONDS = 3.0
DRAG_PIXELS = 6
CLICK_SECONDS = 0.45
TRAIL_SECONDS = 0.6
RIPPLE_SECONDS = 1.1
MAX_RIPPLES = 4


class Stage(QWidget):
    opened = pyqtSignal(str)
    went_home = pyqtSignal()
    scrolled = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName("JARVIS globe")
        self.setAccessibleDescription("Press Enter or Down to see the sections.")
        self.setMinimumSize(design.MIN_WIDTH, design.MIN_HEIGHT)
        self.budget = design.current_budget()
        self.stars = StarField()
        self.stars.set_count(self.budget.particles)
        self.globe = Globe(self.budget.points)
        self.world = World(NAMES)
        self.bubbles = {}
        for name in NAMES:
            b = Bubble(name, self)
            b.clicked.connect(lambda _=False, n=name: self.pick(n))
            b.navigate.connect(self.move_focus)
            b.setMouseTracking(True)
            b.installEventFilter(self)
            self.bubbles[name] = b
        self.progress = 0.0
        self.target = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._set_progress)
        self.state = "idle"
        self.cursor_override = None
        self.cursor_unit = (0.0, 0.0)
        self.cursor_px = None
        self.engaged = 0.0
        self.last_move = 0.0
        self._last_px = None
        self.trail = deque(maxlen=32)
        self.ripples = []
        self.press = None
        self.dragged = False
        self._glow = None
        self._glow_v = -1
        self.setMouseTracking(True)
        self._last = time.monotonic()
        self._wheel_at = 0.0
        self.frame_times = []
        self.globe_rect = QRectF()
        self.apply_budget(self.budget)
        self._layout()

    # ---------- state and budget ----------
    def set_state(self, name):
        self.state = name
        self.globe.set_state(name)

    def apply_budget(self, budget):
        self.budget = budget
        self.stars.set_count(budget.particles)
        if self.globe.n != budget.points:
            self.globe.set_points(budget.points)
        self.update()

    @property
    def section(self):
        return "bubbles" if self.target >= 0.5 else "globe"

    # ---------- scrolling ----------
    def _set_progress(self, v):
        self.progress = float(v)
        self._place()
        self.update()

    def scroll_to(self, section, instant=False):
        target = 1.0 if section == "bubbles" else 0.0
        if target == self.target and self.anim.state() != QVariantAnimation.State.Running:
            return
        self.target = target
        self.anim.stop()
        if instant or not self.budget.transitions:
            self._set_progress(target)
            self._sync_focus()
        else:
            self.anim.setDuration(design.MOTION["slow"])
            self.anim.setEasingCurve(design.EASE)
            self.anim.setStartValue(self.progress)
            self.anim.setEndValue(target)
            self.anim.start()
            self._sync_focus()
        self.scrolled.emit(self.section)

    def _sync_focus(self):
        on = self.target >= 0.5
        for b in self.bubbles.values():
            b.setFocusPolicy(Qt.FocusPolicy.StrongFocus if on else Qt.FocusPolicy.NoFocus)
        if on:
            if not any(b.hasFocus() for b in self.bubbles.values()):
                first = self.bubbles[NAMES[0]]
                first.setFocus(Qt.FocusReason.TabFocusReason) if self.hasFocus() or self.isActiveWindow() else None
        elif any(b.hasFocus() for b in self.bubbles.values()):
            self.setFocus(Qt.FocusReason.OtherFocusReason)

    def wheelEvent(self, ev):
        now = time.monotonic()
        dy = ev.angleDelta().y()
        if dy and now - self._wheel_at > WHEEL_COOLDOWN:
            if dy < 0 and self.section == "globe":
                self._wheel_at = now
                self.scroll_to("bubbles")
            elif dy > 0 and self.section == "bubbles":
                self._wheel_at = now
                self.scroll_to("globe")
        ev.accept()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k in (Qt.Key.Key_Down, Qt.Key.Key_PageDown, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space) and self.section == "globe":
            self.scroll_to("bubbles")
        elif k in (Qt.Key.Key_Up, Qt.Key.Key_PageUp, Qt.Key.Key_Home, Qt.Key.Key_Escape) and self.section == "bubbles":
            self.scroll_to("globe")
        else:
            super().keyPressEvent(ev)
            return
        ev.accept()

    def mousePressEvent(self, ev):
        pos = QPointF(ev.position())
        self.add_ripple(pos)
        self.note_move(pos)
        if ev.button() == Qt.MouseButton.LeftButton:
            self.press = (pos, time.monotonic(), self.section == "globe" and self.globe_rect.contains(pos))
            self.dragged = False
        ev.accept()

    def mouseMoveEvent(self, ev):
        pos = QPointF(ev.position())
        self.note_move(pos)
        if self.press and self.press[2] and self.budget.cursor and ev.buttons() & Qt.MouseButton.LeftButton:
            start = self.press[0]
            if not self.dragged and math.hypot(pos.x() - start.x(), pos.y() - start.y()) > DRAG_PIXELS:
                self.dragged = True
                self.press = (pos, self.press[1], True)
                self.globe.dragging = True
            elif self.dragged:
                last = self._drag_last
                self.globe.drag(pos.x() - last.x(), pos.y() - last.y(), self.globe_rect.width() / 2, max(1 / 120, time.monotonic() - self._drag_t))
            self._drag_last, self._drag_t = pos, time.monotonic()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        press, self.press = self.press, None
        if self.dragged:
            self.globe.release(self.budget.inertia)
        elif press and press[2] and time.monotonic() - press[1] < CLICK_SECONDS * 2 and self.section == "globe":
            self.scroll_to("bubbles")
        self.dragged = False
        ev.accept()

    _drag_last = QPointF()
    _drag_t = 0.0

    def eventFilter(self, obj, ev):
        """A click on a bubble makes a ripple too, wherever on the screen it lands."""
        if ev.type() == QEvent.Type.MouseButtonPress and isinstance(obj, Bubble):
            self.add_ripple(QPointF(obj.mapTo(self, ev.position().toPoint())))
        elif ev.type() == QEvent.Type.MouseMove and isinstance(obj, Bubble):
            self.note_move(QPointF(obj.mapTo(self, ev.position().toPoint())))
        return super().eventFilter(obj, ev)

    # ---------- cursor effects ----------
    def note_move(self, pos):
        """Remember that the pointer moved (from an event or from the poll), which keeps the effects engaged."""
        last = self._last_px
        if last is None or math.hypot(pos.x() - last[0], pos.y() - last[1]) > 0.5:
            self.last_move = time.monotonic()
            self._last_px = (pos.x(), pos.y())

    def add_ripple(self, pos):
        if not self.budget.ripples:
            return
        self.ripples.append((QPointF(pos), time.monotonic()))
        del self.ripples[:-MAX_RIPPLES]
        self.stars.shock((pos.x(), pos.y()))

    def _glow_pixmap(self):
        if self._glow is None or self._glow_v != design.version[0]:
            self._glow_v = design.version[0]
            size = 96
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            p = QPainter(pm)
            g = QRadialGradient(QPointF(size / 2, size / 2), size / 2)
            c0, c1 = QColor(design.ACCENT), QColor(design.ACCENT)
            c0.setAlphaF(0.55)
            c1.setAlphaF(0.0)
            g.setColorAt(0, c0)
            g.setColorAt(1, c1)
            p.fillRect(pm.rect(), g)
            p.end()
            self._glow = pm
        return self._glow

    # ---------- bubbles ----------
    def pick(self, name):
        if name == "Home":
            self.scroll_to("globe")
            self.went_home.emit()
        else:
            self.opened.emit(name)

    def move_focus(self, current, direction):
        target = neighbour(list(self.bubbles.values()), current, direction)
        if target is not None:
            target.setFocus(Qt.FocusReason.TabFocusReason)
        elif direction == "up":
            self.scroll_to("globe")

    def _layout(self):
        w, h = max(1, self.width()), max(1, self.height())
        self.stars.resize(w, h)
        self.world.layout(w, h)
        for b in self.bubbles.values():
            b.fit(self.world.r, self.world.rc)
        self._place()

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._layout()

    def _place(self):
        h = self.height()
        shift = (1 - self.progress) * h
        for body in self.world.bodies:
            b = self.bubbles[body.key]
            b.move(round(body.x - self.world.rc), round(body.y - self.world.rc + shift))
            b.setVisible(self.progress > 0.002)

    # ---------- frame ----------
    def _cursor(self):
        """The pointer in pixels, or None. Read from QCursor every frame, so it works even when this widget gets no move events (xcb under Wayland)."""
        if self.cursor_override is not None:
            return QPointF(*self.cursor_override)
        if not self.isVisible():
            return None
        pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        return pos if self.rect().adjusted(-40, -40, 40, 40).contains(pos.toPoint()) else None

    def tick(self, dt=None):
        now = time.monotonic()
        if dt is None:
            dt = min(0.1, now - self._last)
        self._last = now
        pos = self._cursor()
        if pos is not None:
            self.note_move(pos)
        w, h = max(1, self.width()), max(1, self.height())
        near = pos is not None
        active = near and self.budget.cursor and (now - self.last_move < IDLE_SECONDS or self.dragged)
        self.engaged += ((1.0 if active else 0.0) - self.engaged) * min(1.0, dt * (4.0 if active else 0.9))
        if not self.budget.cursor:
            self.engaged = 0.0
        if self.engaged < 0.004 and not active:
            self.engaged = 0.0
        raw = (max(-1.0, min(1.0, (pos.x() / w - 0.5) * 2)), max(-1.0, min(1.0, (pos.y() / h - 0.5) * 2))) if near else (0.0, 0.0)
        e = self.engaged
        unit = (raw[0] * e, raw[1] * e) if self.budget.parallax else (0.0, 0.0)
        tilt = (raw[0] * e, raw[1] * e) if self.budget.tilt else (0.0, 0.0)
        self.cursor_unit = unit
        self.cursor_px = (pos.x(), pos.y()) if near else None
        repel = self.cursor_px if (self.budget.drift and e > 0.05) else None
        self.stars.step(dt, repel, self.budget.drift)
        self.globe.aim(self.cursor_px, e)
        self.globe.step(dt, tilt, events.level, events.out_level, self.budget.spin)
        if near and e > 0.05 and self.budget.trail:
            if not self.trail or math.hypot(pos.x() - self.trail[-1][0], pos.y() - self.trail[-1][1]) > 4:
                self.trail.append((pos.x(), pos.y(), now))
        while self.trail and (now - self.trail[0][2] > TRAIL_SECONDS or len(self.trail) > max(1, self.budget.trail)):
            self.trail.popleft()
        self.ripples = [r for r in self.ripples if now - r[1] < RIPPLE_SECONDS]
        if self.progress > 0.002:
            self.world.step(dt, self.budget.drift, any(b.lit() for b in self.bubbles.values()))
            instant = not self.budget.transitions
            for b in self.bubbles.values():
                b.ease(dt, instant)
            self._place()
        self.update()

    def _paint_effects(self, p):
        now = time.monotonic()
        if self.trail and self.engaged > 0.02:
            glow = self._glow_pixmap()
            for x, y, t in self.trail:
                age = (now - t) / TRAIL_SECONDS
                if age >= 1:
                    continue
                size = int(18 + 46 * (1 - age))
                p.setOpacity(0.30 * (1 - age) * min(1.0, self.engaged * 1.5))
                p.drawPixmap(int(x - size / 2), int(y - size / 2), size, size, glow)
            p.setOpacity(1.0)
        for pos, t0 in self.ripples:
            age = (now - t0) / RIPPLE_SECONDS
            for k, delay in enumerate((0.0, 0.18)):
                a = age - delay
                if a <= 0 or a >= 1 or (k and self.budget.fps < 30):
                    continue
                f = 1 - (1 - a) ** 3
                c = QColor(design.ACCENT)
                c.setAlphaF(0.55 * (1 - a))
                p.setPen(QPen(c, 1.6))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = 10 + 230 * f
                p.drawEllipse(pos, r, r)

    def greeting_text(self):
        return status.greeting()

    def _paint_orbits(self, p):
        """Two faint ellipses that the bubbles travel on."""
        wd = self.world
        cx, cy = wd.w / 2, max(1.0, wd.h - BOTTOM_RESERVE) / 2
        shift = (1 - self.progress) * self.height()
        c = QColor("#ffffff")
        c.setAlphaF(0.05 * min(1.0, self.progress * 1.5))
        p.setPen(QPen(c, 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        for f in (1.0, wd.INNER):
            p.drawEllipse(QPointF(cx, cy + shift), wd.rx * f, wd.ry * f)

    def paintEvent(self, ev):
        t0 = time.perf_counter()
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.drawPixmap(0, 0, design.backdrop(w, h))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.stars.paint(p, self.cursor_unit, self.budget.parallax, -self.progress * h * 0.35)
        if self.progress > 0.01:
            self._paint_orbits(p)
        if self.progress < 0.998:
            p.save()
            p.translate(0, -self.progress * h * 0.55)
            p.setOpacity(max(0.0, 1 - self.progress * 1.25))
            self.globe_rect = self.globe.paint(p, QRectF(0, 0, w, h - design.SPACE["xl"]))
            p.restore()
            if self.hasFocus() and self.progress < 0.5:
                p.setPen(QPen(QColor(design.ACCENT), 2))
                p.setBrush(Qt.BrushStyle.NoBrush)
                r = self.globe_rect.adjusted(-10, -10, 10, 10)
                p.drawEllipse(r)
            p.setOpacity(max(0.0, 1 - self.progress * 2.0))
            p.setFont(design.font(24))
            p.setPen(QColor(design.TEXT))
            p.drawText(QRectF(0, design.SPACE["l"], w, 40), Qt.AlignmentFlag.AlignHCenter, self.greeting_text())
            p.setFont(design.font(13))
            p.setPen(QColor(design.DIM))
            p.drawText(QRectF(0, h - 140, w, 24), Qt.AlignmentFlag.AlignHCenter, "Scroll down, click the globe or press Enter")
            p.setOpacity(1.0)
        self._paint_effects(p)
        p.end()
        self.frame_times.append(time.perf_counter() - t0)
        del self.frame_times[:-240]
