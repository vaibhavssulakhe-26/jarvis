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


def readable(colour, background=None, ratio=MIN_CONTRAST + 0.1):
    """The colour, lightened towards white until it reads at the ratio on the background (by default on both the page and the panel colour of the
    current background). Used for any accent the user picks."""
    c = QColor(colour)
    backs = [background] if background is not None else [BG, PANEL]
    for _ in range(40):
        if all(contrast(c, b) >= ratio for b in backs):
            break
        c = QColor(int(c.red() + (255 - c.red()) * 0.1), int(c.green() + (255 - c.green()) * 0.1), int(c.blue() + (255 - c.blue()) * 0.1))
    return c


ACCENT_DEFAULT = "#8c9dff"
ACCENT_PRESETS = {"Indigo": "#8c9dff", "Sky": "#4cc2ff", "Mint": "#4de3b0", "Amber": "#ffb84d", "Rose": "#ff7aa8", "Violet": "#b48cff"}
BACKGROUNDS = {
    "indigo": {"label": "Indigo depth", "bg": "#06070b", "depth": "#161a45", "panel": "#10121c"},
    "graphite": {"label": "Graphite", "bg": "#08090b", "depth": "#22252d", "panel": "#111317"},
    "ocean": {"label": "Deep ocean", "bg": "#050a12", "depth": "#0e2e4d", "panel": "#0b1520"},
    "plum": {"label": "Plum", "bg": "#0a0710", "depth": "#34154a", "panel": "#140e1c"},
    "black": {"label": "Pure black", "bg": "#000000", "depth": "#0b0c18", "panel": "#0c0c10"},
}
THEMES = {
    "indigo": {"label": "Indigo (default)", "accent": "#8c9dff", "background": "indigo", "classic": "ice"},
    "ocean": {"label": "Ocean", "accent": "#4cc2ff", "background": "ocean", "classic": "cyan"},
    "forest": {"label": "Forest", "accent": "#4de3b0", "background": "graphite", "classic": "green"},
    "ember": {"label": "Ember", "accent": "#ffb84d", "background": "black", "classic": "amber"},
    "rose": {"label": "Rose", "accent": "#ff7aa8", "background": "plum", "classic": "pink"},
}
GLOBE_OPTIONS = {"density": ("sparse", "normal", "dense"), "size": ("small", "normal", "large"), "glow": ("soft", "normal", "strong")}
GLOBE_FACTORS = {"density": {"sparse": 0.6, "normal": 1.0, "dense": 1.35}, "size": {"small": 0.27, "normal": 0.34, "large": 0.40}, "glow": {"soft": 0.55, "normal": 1.0, "strong": 1.45}}
CHAT_SIZES = (10, 11, 12, 13, 14)
CHAT_DENSITY = ("comfortable", "compact")
DEFAULTS = {"accent": ACCENT_DEFAULT, "background": "indigo", "globe": {"density": "normal", "size": "normal", "glow": "normal"}, "intensity": 100,
            "chat": {"size": 11, "density": "comfortable"}}
listeners = []
version = [0]


def settings():
    """The saved look (settings.json, ui2) with every key present and every value valid."""
    from ..voice import voices
    saved = voices.read_settings().get("ui2")
    saved = saved if isinstance(saved, dict) else {}
    out = {"accent": DEFAULTS["accent"], "background": "indigo", "globe": dict(DEFAULTS["globe"]), "intensity": 100, "chat": dict(DEFAULTS["chat"])}
    if isinstance(saved.get("accent"), str) and saved["accent"].startswith("#") and QColor(saved["accent"]).isValid():
        out["accent"] = QColor(saved["accent"]).name()
    if saved.get("background") in BACKGROUNDS:
        out["background"] = saved["background"]
    g = saved.get("globe") if isinstance(saved.get("globe"), dict) else {}
    for k, opts in GLOBE_OPTIONS.items():
        if g.get(k) in opts:
            out["globe"][k] = g[k]
    try:
        out["intensity"] = max(0, min(100, int(saved.get("intensity", 100))))
    except (TypeError, ValueError):
        pass
    c = saved.get("chat") if isinstance(saved.get("chat"), dict) else {}
    if c.get("size") in CHAT_SIZES:
        out["chat"]["size"] = c["size"]
    if c.get("density") in CHAT_DENSITY:
        out["chat"]["density"] = c["density"]
    return out


def apply():
    """Make the saved look the current one: the background colours, then the accent lifted until it reads on that background. Caches are dropped."""
    global BG, BG_DEPTH, PANEL, ACCENT
    s = settings()
    bg = BACKGROUNDS[s["background"]]
    BG, BG_DEPTH, PANEL = bg["bg"], bg["depth"], bg["panel"]
    ACCENT = readable(s["accent"]).name()
    _cache["bg"] = None
    _cache["glass"].clear()
    version[0] += 1


def update(**changes):
    """Save a change to the look (accent, background, globe, intensity, chat; globe and chat take partial dicts), apply it now and tell the listeners."""
    from ..voice import voices
    cur = settings()
    if "accent" in changes and QColor(str(changes["accent"])).isValid():
        cur["accent"] = QColor(str(changes["accent"])).name()
    if changes.get("background") in BACKGROUNDS:
        cur["background"] = changes["background"]
    for key in ("globe", "chat"):
        if isinstance(changes.get(key), dict):
            cur[key].update(changes[key])
    if "intensity" in changes:
        cur["intensity"] = changes["intensity"]
    data = voices.read_settings()
    data["ui2"] = cur
    voices.write_settings(data)
    apply()
    for fn in list(listeners):
        try:
            fn()
        except Exception:
            pass
    return settings()


def apply_theme(key):
    spec = THEMES[key]
    return update(accent=spec["accent"], background=spec["background"])


def globe_look():
    """(size as a fraction of the screen, glow multiplier) for the globe."""
    g = settings()["globe"]
    return GLOBE_FACTORS["size"][g["size"]], GLOBE_FACTORS["glow"][g["glow"]]


def pages_qss():
    """Dark glass for the widgets the older page style leaves white: tables, plain text boxes, headers, check boxes and drop-down lists."""
    return f"""
    QTableWidget, QPlainTextEdit {{ background: rgba(255,255,255,0.04); color: {TEXT}; border: 1px solid rgba(255,255,255,0.12); border-radius: {RADIUS['s']}px;
        gridline-color: rgba(255,255,255,0.06); selection-background-color: rgba(140,157,255,0.30); selection-color: {TEXT}; }}
    QTableWidget::item {{ padding: 4px 8px; }}
    QTableWidget::item:selected {{ background: rgba(140,157,255,0.30); color: {TEXT}; }}
    QHeaderView::section {{ background: transparent; color: {DIM}; border: none; border-bottom: 1px solid rgba(255,255,255,0.12); padding: 6px 8px; }}
    QTableCornerButton::section {{ background: transparent; border: none; }}
    QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px; border: 1px solid rgba(255,255,255,0.45); background: transparent; }}
    QCheckBox::indicator:checked {{ background: {ACCENT}; border: 1px solid {ACCENT}; }}
    QCheckBox::indicator:focus {{ border: 2px solid {ACCENT}; }}
    QComboBox QAbstractItemView {{ background: {PANEL}; color: {TEXT}; border: 1px solid rgba(255,255,255,0.2); selection-background-color: rgba(140,157,255,0.30); }}
    QComboBox {{ background: rgba(255,255,255,0.05); color: {TEXT}; border: 1px solid rgba(255,255,255,0.14); border-radius: {RADIUS['s']}px; padding: 5px 10px; }}
    QComboBox:focus, QPlainTextEdit:focus, QTableWidget:focus {{ border: 2px solid {ACCENT}; }}
    """


def chat_qss():
    """Style for the chat bubbles: text size and spacing."""
    c = settings()["chat"]
    pad = 6 if c["density"] == "compact" else 12
    return (f"QFrame#bubble_user QLabel, QFrame#bubble_bot QLabel {{ font-size: {c['size']}pt; }} "
            f"QFrame#bubble_user, QFrame#bubble_bot {{ padding: {pad}px; }}")


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
    tilt: bool = True
    trail: int = 16
    ripples: bool = True
    inertia: bool = True
    cursor: bool = True


def budget(low=False, reduced=False, intensity=100, density=1.0, busy=False):
    """Reduced motion keeps what the hand drives (the light spot, dragging the globe) and drops what moves by itself: tilt, parallax, particles, trail, ripples, inertia."""
    i = max(0, min(100, intensity)) / 100
    if busy:
        return Budget(15, 0, int(420 * density), False, False, True, 0.3, False, 0, False, False, False)
    if reduced:
        return Budget(15, 0, int((420 if low else 700) * density), False, False, False, 0.0, False, 0, False, False)
    if low:
        return Budget(15, int(80 * i), int(420 * density), i > 0, i > 0, True, 0.3 + 0.7 * i, True, round(6 * i), True, True)
    return Budget(30, int(300 * i), int(1100 * density), i > 0, i > 0, True, 0.3 + 0.7 * i, True, round(16 * i), True, True)


def low_power():
    return bool(themes.load()[2].get("low_power"))


def reduced_motion():
    return bool(themes.load()[2].get("reduced_motion"))


def current_budget():
    s = settings()
    from ..brain import local
    return budget(low_power(), reduced_motion(), s["intensity"], GLOBE_FACTORS["density"][s["globe"]["density"]], busy=local.generating())


_cache = {"bg": None, "glass": {}}


def backdrop(w, h):
    """Near-black with a soft depth colour behind the middle of the screen, rendered once per size and background."""
    key = (w, h, version[0])
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
    key = (w, h, radius, hot, version[0])
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


apply()
