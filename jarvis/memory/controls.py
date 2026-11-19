"""What Jarvis may remember: a pause switch and one switch per category, saved in data/settings.json under "memory". The ordinary categories are on;
the sensitive ones (other people, health) are off until the user turns them on. Passwords, keys, card and id numbers are never stored whatever these say."""
from ..core import config, jsonfile

NORMAL = ("preference", "project", "goal", "plan", "decision", "routine", "fact")
SENSITIVE = ("people", "health")
CATEGORIES = NORMAL + SENSITIVE
NEVER = "passwords, keys, card numbers and id numbers"
LABELS = {"preference": "Preferences", "project": "Projects", "goal": "Goals", "plan": "Plans", "decision": "Decisions", "routine": "Routines",
          "fact": "General facts", "people": "Other people", "health": "Health"}


def _path():
    return config.DATA / "settings.json"


def defaults():
    return {"paused": False, "categories": {c: c not in SENSITIVE for c in CATEGORIES}}


def load():
    saved = jsonfile.read(_path(), {}, dict).get("memory")
    out = defaults()
    if isinstance(saved, dict):
        out["paused"] = bool(saved.get("paused", False))
        cats = saved.get("categories")
        if isinstance(cats, dict):
            out["categories"].update({k: bool(v) for k, v in cats.items() if k in CATEGORIES})
    return out


def _save(data):
    whole = jsonfile.read(_path(), {}, dict)
    whole["memory"] = data
    jsonfile.write(_path(), whole)


def paused():
    return load()["paused"]


def set_paused(on):
    data = load()
    data["paused"] = bool(on)
    _save(data)


def allows(category):
    """Whether a category may be written right now: not paused and its switch is on. An unknown category counts as a general fact."""
    data = load()
    if data["paused"]:
        return False
    return data["categories"].get(category if category in CATEGORIES else "fact", True)


def set_category(category, on):
    if category not in CATEGORIES:
        raise ValueError(category)
    data = load()
    data["categories"][category] = bool(on)
    _save(data)


def refusal(category=""):
    """The sentence to say when a write is refused, naming the switch to turn."""
    if paused():
        return "Remembering is paused. You can resume it in Settings, Memory."
    return f"I am not remembering {LABELS.get(category, 'that').lower()} right now. You can turn it on in Settings, Memory."
