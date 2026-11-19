"""The design system of the new window: tokens (colour, spacing, radius, motion), pre-rendered backdrop and glass, the motion budget and the
settings that cut it. Every colour of the globe screen, the bubbles, the bottom panel and the palette comes from here."""
from dataclasses import dataclass

from PyQt6.QtCore import QEasingCurve, QPointF, QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient

from .dashboard import themes

BG = "#06070b"
BG_DEPTH = "#161a45"
PANEL = "#10121c"
TEXT = "#e9ecf8"
DIM = "#9aa2c0"
ACCENT = "#8c9dff"
ON_ACCENT = "#06070b"
OK = "#5fe3a1"
WARN = "#ffc266"
ERROR = "#ff7a88"
OFFLINE = "#8189a6"
MIN_CONTRAST = 4.5

SPACE = {"xs": 4, "s": 8, "m": 16, "l": 24, "xl": 40}
RADIUS = {"s": 8, "m": 14, "l": 22}
MOTION = {"fast": 120, "base": 240, "slow": 520}
EASE = QEasingCurve.Type.OutCubic
FONT_FAMILIES = ["Inter", "Noto Sans", "Cantarell", "DejaVu Sans", "sans-serif"]
MIN_WIDTH, MIN_HEIGHT = 720, 520


def font(size=11, weight=QFont.Weight.Light):
    f = QFont()
    f.setFamilies(FONT_FAMILIES)
    f.setPixelSize(size)
    f.setWeight(weight)
    return f


def _lin(v):
    v = v / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def luminance(colour):
    c = QColor(colour)
    return 0.2126 * _lin(c.red()) + 0.7152 * _lin(c.green()) + 0.0722 * _lin(c.blue())


def contrast(a, b):
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def readable(colour, background=BG, ratio=MIN_CONTRAST + 0.1):
    """The colour, lightened towards white until it reads at the ratio on the background. Used for any accent the user picks."""
    c = QColor(colour)
    white = QColor("#ffffff")
    for _ in range(24):
        if contrast(c, background) >= ratio:
            break
        c = QColor(int(c.red() + (255 - c.red()) * 0.1), int(c.green() + (255 - c.green()) * 0.1), int(c.blue() + (255 - c.blue()) * 0.1))
    return c


def accent():
    """The accent colour. Saved in settings.json under ui2.accent once a later phase lets the user change it."""
    from ..voice import voices
    ui2 = voices.read_settings().get("ui2")
    saved = ui2.get("accent") if isinstance(ui2, dict) else None
    return readable(saved) if saved and QColor(saved).isValid() else QColor(ACCENT)


def contrast_pairs():
    """(name, foreground, background) pairs that must read at MIN_CONTRAST or better."""
    pairs = []
    for bg_name, bg in (("bg", BG), ("panel", PANEL)):
        for name, fg in (("text", TEXT), ("dim", DIM), ("accent", ACCENT), ("ok", OK), ("warn", WARN), ("error", ERROR)):
            pairs.append((f"{name} on {bg_name}", fg, bg))
    pairs.append(("on-accent on accent", ON_ACCENT, ACCENT))
    pairs.append(("offline text on bg", OFFLINE, BG))
    return pairs


@dataclass(frozen=True)
class Budget:
    """What the animation may spend. Low power cuts frames, particles and globe points; reduced motion also stops drift, parallax and transitions."""
    fps: int
    particles: int
    points: int
    drift: bool
    parallax: bool
    transitions: bool
    spin: float


def budget(low=False, reduced=False):
    if reduced:
        return Budget(15, 0, 420 if low else 700, False, False, False, 0.0)
    if low:
        return Budget(15, 80, 420, True, True, True, 1.0)
    return Budget(30, 300, 1100, True, True, True, 1.0)


def low_power():
    return bool(themes.load()[2].get("low_power"))


def reduced_motion():
    return bool(themes.load()[2].get("reduced_motion"))


def current_budget():
    return budget(low_power(), reduced_motion())


_cache = {"bg": None, "glass": {}}


def backdrop(w, h):
    """Near-black with a soft indigo depth behind the middle of the screen, rendered once per size."""
    key = (w, h)
    if _cache["bg"] and _cache["bg"][0] == key:
        return _cache["bg"][1]
    pm = QPixmap(max(1, w), max(1, h))
    p = QPainter(pm)
    lin = QLinearGradient(0, 0, 0, h)
    lin.setColorAt(0, QColor("#090a12"))
    lin.setColorAt(1, QColor(BG))
    p.fillRect(pm.rect(), lin)
    rad = QRadialGradient(QPointF(w / 2, h * 0.45), max(w, h) * 0.7)
    c0, c1 = QColor(BG_DEPTH), QColor(BG_DEPTH)
    c0.setAlpha(210)
    c1.setAlpha(0)
    rad.setColorAt(0, c0)
    rad.setColorAt(1, c1)
    p.fillRect(pm.rect(), rad)
    p.end()
    _cache["bg"] = (key, pm)
    return pm


def glass(w, h, radius=RADIUS["m"], hot=False):
    """A floating panel: faint fill, one soft border, a thin top highlight. Rendered once per size; nothing blurs live."""
    key = (w, h, radius, hot)
    cache = _cache["glass"]
    if key in cache:
        return cache[key]
    if len(cache) > 48:
        cache.clear()
    pm = QPixmap(max(1, w), max(1, h))
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    r = QRectF(0.5, 0.5, w - 1, h - 1)
    fill = QLinearGradient(0, 0, 0, h)
    top, bottom = QColor(PANEL), QColor(PANEL)
    top.setAlpha(235 if hot else 215)
    bottom.setAlpha(250 if hot else 235)
    fill.setColorAt(0, top)
    fill.setColorAt(1, bottom)
    p.setBrush(fill)
    edge = QColor(ACCENT if hot else "#ffffff")
    edge.setAlpha(120 if hot else 34)
    p.setPen(QPen(edge, 1))
    p.drawRoundedRect(r, radius, radius)
    shine = QColor("#ffffff")
    shine.setAlpha(14)
    p.setPen(QPen(shine, 1))
    p.drawLine(QPointF(radius, 1.5), QPointF(w - radius, 1.5))
    p.end()
    cache[key] = pm
    return pm


def qss():
    """Chrome shared by the shell: flat glass buttons and a clearly visible focus ring."""
    return f"""
    QWidget {{ color: {TEXT}; font-family: "Inter", "Noto Sans", "Cantarell", sans-serif; font-weight: 300; }}
    QPushButton, QToolButton {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.12); border-radius: {RADIUS['s']}px;
        padding: 6px 14px; color: {TEXT}; }}
    QPushButton:hover, QToolButton:hover {{ background: rgba(255,255,255,0.10); }}
    QPushButton:focus, QToolButton:focus {{ border: 2px solid {ACCENT}; padding: 5px 13px; }}
    QLineEdit {{ background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.14); border-radius: {RADIUS['s']}px; padding: 8px 12px;
        color: {TEXT}; selection-background-color: {ACCENT}; selection-color: {ON_ACCENT}; }}
    QLineEdit:focus {{ border: 2px solid {ACCENT}; padding: 7px 11px; }}
    QListWidget {{ background: transparent; border: none; outline: none; }}
    QListWidget::item {{ padding: 8px 12px; border-radius: {RADIUS['s']}px; color: {TEXT}; }}
    QListWidget::item:selected {{ background: rgba(140,157,255,0.20); color: {TEXT}; border: 1px solid {ACCENT}; }}
    QLabel#dim {{ color: {DIM}; }}
    """
