"""Theme presets and the saved choice. No Qt here, so voice commands work with or without the window."""
import colorsys
import json
import random

from ...voice import voices

PRESETS = {
    "cyan": dict(accent="#19d8ff", secondary="#5b8cff", bg="#050a14", panel="#0c1a2e", glow=1.0),
    "green": dict(accent="#2dff9a", secondary="#b8ff4d", bg="#040d0b", panel="#0a2019", glow=1.0),
    "amber": dict(accent="#ffb02e", secondary="#ff6a1a", bg="#0b0a07", panel="#241a0a", glow=0.9),
    "red": dict(accent="#e0566a", secondary="#d98a5e", bg="#0c0609", panel="#26111a", glow=0.9),
    "purple": dict(accent="#b36bff", secondary="#6b7dff", bg="#080614", panel="#1a1034", glow=1.0),
    "pink": dict(accent="#ff5fb8", secondary="#ffa05f", bg="#0d0610", panel="#2a0f26", glow=1.0),
    "ice": dict(accent="#a9e4ff", secondary="#7fa6ff", bg="#050a12", panel="#101f33", glow=0.9),
    "white": dict(accent="#e8f1ff", secondary="#9db4d6", bg="#07090d", panel="#161c26", glow=0.7),
}
ORDER = list(PRESETS)
SEMANTIC = dict(ok="#3ddc84", warn="#ffb02e", bad="#ff4d5e", white="#ffffff")
STATE_TINT = {"listening": "#7ff0ff", "thinking": "#ffb02e", "error": "#ff3b4e"}
DEFAULT_UI = dict(state_colours=False, cycle=False, low_power=False)


def from_hue(hue):
    h = (float(hue) % 360) / 360.0

    def hex_(hh, s, v):
        r, g, b = colorsys.hsv_to_rgb(hh % 1.0, s, v)
        return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))
    return dict(accent=hex_(h, 0.85, 1.0), secondary=hex_(h + 0.09, 0.7, 1.0), bg=hex_(h, 0.6, 0.07),
                panel=hex_(h, 0.7, 0.2), glow=1.0)


def load():
    """(preset name or 'custom', hue, ui flags) from data/settings.json."""
    try:
        data = json.loads(voices.SETTINGS.read_text())
    except (OSError, ValueError):
        data = {}
    t = data.get("theme") if isinstance(data.get("theme"), dict) else {}
    name = t.get("name") if t.get("name") in PRESETS or t.get("name") == "custom" else "cyan"
    ui = dict(DEFAULT_UI)
    if isinstance(data.get("ui"), dict):
        ui.update({k: bool(v) for k, v in data["ui"].items() if k in DEFAULT_UI})
    try:
        hue = float(t.get("hue", 190))
    except (TypeError, ValueError):
        hue = 190.0
    return name, hue, ui


def save(name=None, hue=None, **ui):
    """Merge the theme and UI flags into settings.json, leaving the other keys (voice and so on) alone."""
    try:
        data = json.loads(voices.SETTINGS.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    cur_name, cur_hue, cur_ui = load()
    if name is not None:
        data["theme"] = {"name": name, "hue": float(hue if hue is not None else cur_hue)}
    elif hue is not None:
        data["theme"] = {"name": cur_name, "hue": float(hue)}
    if ui:
        cur_ui.update({k: bool(v) for k, v in ui.items() if k in DEFAULT_UI})
        data["ui"] = cur_ui
    voices.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    voices.SETTINGS.write_text(json.dumps(data))


def load_window():
    """The saved window size, or the default 1280 by 760."""
    try:
        w, h = json.loads(voices.SETTINGS.read_text()).get("window", [1280, 760])
        return max(980, min(4000, int(w))), max(640, min(3000, int(h)))
    except (OSError, ValueError, TypeError):
        return 1280, 760


def save_window(w, h):
    try:
        data = json.loads(voices.SETTINGS.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["window"] = [int(w), int(h)]
    voices.SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    voices.SETTINGS.write_text(json.dumps(data))


def preset(name, hue=190.0):
    return from_hue(hue) if name == "custom" else dict(PRESETS.get(name, PRESETS["cyan"]))


def pick(spec, current):
    """The theme name a spoken phrase means: a preset, 'next', 'random', or None."""
    t = str(spec or "").strip().lower()
    if t in PRESETS:
        return t
    if t in ("next", "next one", "another", "change"):
        return ORDER[(ORDER.index(current) + 1) % len(ORDER)] if current in ORDER else ORDER[0]
    if t in ("random", "any", "surprise me"):
        return random.choice([n for n in ORDER if n != current])
    return None
