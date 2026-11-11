"""The live theme: every colour in the dashboard is read from here, and a change fades over 400 ms."""
from PyQt6.QtCore import QObject, QTimer, QVariantAnimation, pyqtSignal
from PyQt6.QtGui import QColor, QPixmap, QRadialGradient, QPainter, QBrush
from PyQt6.QtCore import Qt

from . import themes

FADE_MS = 400
CYCLE_MS = 20000
CYCLE_STEP = 5.0
KEYS = ("accent", "secondary", "bg", "panel")


def lerp(a, b, f):
    return QColor(int(a.red() + (b.red() - a.red()) * f), int(a.green() + (b.green() - a.green()) * f),
                  int(a.blue() + (b.blue() - a.blue()) * f))


def alpha(color, a):
    c = QColor(color)
    c.setAlpha(max(0, min(255, int(a))))
    return c


class Theme(QObject):
    changed = pyqtSignal()

    def __init__(self, name=None, hue=None, ui=None):
        super().__init__()
        saved = themes.load()
        self.name = name or saved[0]
        self.hue = float(saved[1] if hue is None else hue)
        flags = dict(saved[2])
        flags.update(ui or {})
        self.state_colours = flags["state_colours"]
        self.cycle = flags["cycle"]
        self.mode = "idle"
        self.version = 0
        self._glow = {}
        base = themes.preset(self.name, self.hue)
        self.cur = {k: QColor(base[k]) for k in KEYS}
        self.glow_strength = base["glow"]
        self._from = dict(self.cur)
        self._to = dict(self.cur)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(FADE_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.valueChanged.connect(self._step)
        self._anim.finished.connect(self._done)
        self._cycler = QTimer(self)
        self._cycler.timeout.connect(self._cycle_step)
        if self.cycle:
            self._cycler.start(CYCLE_MS)

    # colours the rest of the dashboard reads
    @property
    def accent(self):
        return self.cur["accent"]

    @property
    def secondary(self):
        return self.cur["secondary"]

    @property
    def bg(self):
        return self.cur["bg"]

    @property
    def panel(self):
        return alpha(self.cur["panel"], 150)

    @property
    def text(self):
        return lerp(QColor(themes.SEMANTIC["white"]), self.cur["accent"], 0.18)

    @property
    def dim(self):
        return lerp(self.cur["bg"], self.cur["accent"], 0.55)

    @property
    def ok(self):
        return QColor(themes.SEMANTIC["ok"])

    @property
    def warn(self):
        return QColor(themes.SEMANTIC["warn"])

    @property
    def bad(self):
        return QColor(themes.SEMANTIC["bad"])

    def preset_colours(self):
        base = themes.preset(self.name, self.hue)
        target = {k: QColor(base[k]) for k in KEYS}
        if self.state_colours and self.mode in themes.STATE_TINT:
            target["accent"] = lerp(target["accent"], QColor(themes.STATE_TINT[self.mode]), 0.85)
        return target, base["glow"]

    def retarget(self, animate=True):
        target, glow = self.preset_colours()
        self.glow_strength = glow
        self._anim.stop()
        if not animate:
            self.cur = target
            self._finish()
            return
        self._from = dict(self.cur)
        self._to = target
        self._anim.start()

    def _step(self, f):
        self.cur = {k: lerp(self._from[k], self._to[k], f) for k in KEYS}
        self.changed.emit()

    def _done(self):
        self.cur = dict(self._to)
        self._finish()

    def _finish(self):
        self.version += 1
        self._glow.clear()
        self.changed.emit()

    # changes
    def set_name(self, name, animate=True):
        self.name = name
        self.retarget(animate)

    def set_hue(self, hue, animate=True, save=True):
        self.name, self.hue = "custom", float(hue) % 360
        self.retarget(animate)
        if save:
            themes.save("custom", self.hue)

    def set_state(self, mode):
        mode = mode if mode in themes.STATE_TINT else "idle"
        if mode != self.mode:
            self.mode = mode
            if self.state_colours:
                self.retarget()

    def set_flags(self, state_colours=None, cycle=None):
        if state_colours is not None:
            self.state_colours = bool(state_colours)
            self.retarget()
        if cycle is not None:
            self.cycle = bool(cycle)
            self._cycler.start(CYCLE_MS) if self.cycle else self._cycler.stop()

    def _cycle_step(self):
        base_hue = self.hue if self.name == "custom" else QColor(themes.PRESETS[self.name]["accent"]).hueF() * 360
        self.set_hue(base_hue + CYCLE_STEP, save=False)

    def reload_saved(self):
        name, hue, ui = themes.load()
        if (name, hue) != (self.name, self.hue):
            self.name, self.hue = name, hue
            self.retarget()
        self.set_flags(ui["state_colours"], ui["cycle"])

    # one soft round sprite per theme, reused by everything that glows
    def glow(self, size, strength=1.0):
        key = (size, self.cur["accent"].rgb(), round(strength, 2))
        pm = self._glow.get(key)
        if pm is None:
            if len(self._glow) > 24:
                self._glow.clear()
            pm = QPixmap(size, size)
            pm.fill(Qt.GlobalColor.transparent)
            g = QRadialGradient(size / 2, size / 2, size / 2)
            g.setColorAt(0.0, alpha(self.cur["accent"], 255 * strength))
            g.setColorAt(0.35, alpha(self.cur["accent"], 90 * strength))
            g.setColorAt(1.0, alpha(self.cur["accent"], 0))
            p = QPainter(pm)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(g))
            p.drawEllipse(0, 0, size, size)
            p.end()
            self._glow[key] = pm
        return pm

    def qss(self):
        a, t, d = self.accent.name(), self.text.name(), self.dim.name()
        a_soft = alpha(self.accent, 70).name(QColor.NameFormat.HexArgb)
        a_hover = alpha(self.accent, 40).name(QColor.NameFormat.HexArgb)
        field = alpha(self.cur["panel"], 200).name(QColor.NameFormat.HexArgb)
        return f"""
QWidget {{ color: {t}; font-family: "JetBrains Mono", "DejaVu Sans Mono", "Noto Sans Mono", monospace; font-size: 10pt; }}
QLabel {{ background: transparent; }}
QLabel#cap {{ color: {d}; font-size: 8pt; letter-spacing: 2px; }}
QLabel#big {{ color: {a}; font-size: 20pt; }}
QLabel#brand {{ color: {a}; font-size: 12pt; font-weight: bold; letter-spacing: 3px; }}
QLabel#clock {{ color: {t}; font-size: 17pt; letter-spacing: 2px; }}
QLabel#state {{ color: {a}; font-size: 11pt; letter-spacing: 6px; padding: 4px; }}
QMenu {{ background: {self.cur['bg'].name()}; border: 1px solid {a_soft}; padding: 4px; }}
QMenu::item {{ padding: 6px 18px; }}
QMenu::item:selected {{ background: {a_soft}; }}
QPushButton {{ background: {field}; border: 1px solid {a_soft}; border-radius: 6px; padding: 6px 12px; color: {t}; }}
QPushButton:hover {{ background: {a_hover}; border: 1px solid {a}; }}
QPushButton:checked {{ background: {a_soft}; border: 1px solid {a}; }}
QToolButton {{ background: {field}; border: 1px solid {a_soft}; border-radius: 6px; padding: 6px 12px; color: {t}; }}
QToolButton:hover {{ background: {a_hover}; border: 1px solid {a}; }}
QToolButton::menu-indicator {{ image: none; }}
QPushButton#nav {{ text-align: left; padding: 10px 14px; border: none; border-left: 2px solid transparent; border-radius: 0; background: transparent; }}
QPushButton#nav:checked {{ border-left: 2px solid {a}; background: {a_hover}; color: {a}; }}
QPushButton#stop {{ border: 1px solid {self.bad.name()}; color: {self.bad.name()}; }}
QPushButton#talk {{ border: 1px solid {a}; color: {a}; padding: 8px 22px; }}
QLineEdit, QTextEdit, QListWidget, QComboBox {{ background: {field}; border: 1px solid {a_soft}; border-radius: 6px; padding: 5px 8px;
    selection-background-color: {a}; selection-color: {self.cur['bg'].name()}; }}
QLineEdit:focus {{ border: 1px solid {a}; }}
QListWidget::item:selected {{ background: {a_soft}; color: {t}; }}
QScrollBar:vertical {{ background: transparent; width: 8px; }}
QScrollBar::handle:vertical {{ background: {a_soft}; border-radius: 4px; min-height: 20px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
QCheckBox {{ spacing: 8px; background: transparent; }}
QSlider::groove:horizontal {{ height: 4px; background: {a_soft}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {a}; width: 14px; margin: -6px 0; border-radius: 7px; }}
QToolTip {{ background: {self.cur['bg'].name()}; color: {t}; border: 1px solid {a}; }}
"""
