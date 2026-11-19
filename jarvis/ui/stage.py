"""The globe screen: the star field and the globe behind, the seven bubbles one scroll below. One widget, one paint per frame."""
import time

from PyQt6.QtCore import QPointF, QRectF, Qt, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QCursor, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..actions import events
from . import design
from .bubbles import NAMES, Bubble, World, neighbour
from .globe import Globe, StarField

WHEEL_COOLDOWN = 0.45


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
            self.bubbles[name] = b
        self.progress = 0.0
        self.target = 0.0
        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._set_progress)
        self.state = "idle"
        self.cursor_override = None
        self.cursor_unit = (0.0, 0.0)
        self.cursor_px = None
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
        if self.section == "globe" and self.globe_rect.contains(QPointF(ev.position())):
            self.scroll_to("bubbles")
        ev.accept()

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
        if self.cursor_override is not None:
            pos = QPointF(*self.cursor_override)
        elif self.isVisible() and self.window().isActiveWindow():
            pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        else:
            return (0.0, 0.0), None
        w, h = max(1, self.width()), max(1, self.height())
        unit = (max(-1.0, min(1.0, (pos.x() / w - 0.5) * 2)), max(-1.0, min(1.0, (pos.y() / h - 0.5) * 2)))
        return unit, (pos.x(), pos.y())

    def tick(self, dt=None):
        now = time.monotonic()
        if dt is None:
            dt = min(0.1, now - self._last)
        self._last = now
        unit, px = self._cursor()
        if not self.budget.parallax:
            unit = (0.0, 0.0)
        self.cursor_unit, self.cursor_px = unit, px
        self.stars.step(dt, px if self.budget.drift else None, self.budget.drift)
        self.globe.step(dt, unit, events.level, events.out_level, self.budget.spin)
        if self.progress > 0.002:
            self.world.step(dt, self.budget.drift)
            instant = not self.budget.transitions
            for b in self.bubbles.values():
                b.ease(dt, instant)
            self._place()
        self.update()

    def paintEvent(self, ev):
        t0 = time.perf_counter()
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.drawPixmap(0, 0, design.backdrop(w, h))
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.stars.paint(p, self.cursor_unit, self.budget.parallax, -self.progress * h * 0.35)
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
            p.setFont(design.font(13))
            p.setPen(QColor(design.DIM))
            p.drawText(QRectF(0, h - 140, w, 24), Qt.AlignmentFlag.AlignHCenter, "Scroll down, click the globe or press Enter")
            p.setOpacity(1.0)
        p.end()
        self.frame_times.append(time.perf_counter() - t0)
        del self.frame_times[:-240]
