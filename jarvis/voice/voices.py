"""Which Piper voice is in use. The choice is saved in data/settings.json and applies on the next spoken reply."""
import json
import re
from pathlib import Path

from ..core import config

DEFAULT = "en_US-ryan-medium"
DIRS = (config.MODELS / "voices", Path.home() / "piper-voices")
MALE = ("ryan", "joe", "alan", "northern_english_male", "arctic", "danny", "kusal", "john", "bryce")
SETTINGS = config.DATA / "settings.json"


def installed():
    """{voice name: path to its .onnx} for every voice that has its .json next to it."""
    found = {}
    for d in DIRS:
        for p in sorted(d.glob("*.onnx")):
            if p.with_name(p.name + ".json").exists():
                found.setdefault(p.stem, p)
    return found


def gender(name):
    return "male" if any(m in name.lower() for m in MALE) else "female"


def label(name):
    """A speakable name such as 'Ryan, an American male voice'."""
    who = name.split("-")[1].replace("_", " ").title()
    accent = "a British" if name.startswith("en_GB") else "an American"
    return f"{who}, {accent} {gender(name)} voice"


def _saved():
    try:
        return str(json.loads(SETTINGS.read_text()).get("voice") or "")
    except (OSError, ValueError, AttributeError):
        return ""


def first_run_default():
    return config.get("VOICE") or config.get("JARVIS_VOICE") or DEFAULT


def current_name():
    voices = installed()
    for name in (_saved(), first_run_default(), DEFAULT):
        if name in voices:
            return name
    return next(iter(voices), first_run_default())


def current_path():
    return installed().get(current_name())


def choose(name):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(SETTINGS.read_text())
        data = data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        data = {}
    data["voice"] = name
    SETTINGS.write_text(json.dumps(data))


def next_name():
    names = list(installed())
    if not names:
        return None
    cur = current_name()
    return names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]


def find(want):
    """The best installed voice for 'male', 'female', 'british' or part of a voice name."""
    voices = list(installed())
    cur = current_name()
    want = want.lower()
    pool = voices
    if want in ("male", "female"):
        pool = [n for n in voices if gender(n) == want]
    elif want in ("british", "english", "uk"):
        pool = [n for n in voices if n.startswith("en_GB")]
    elif want in ("american", "us"):
        pool = [n for n in voices if n.startswith("en_US")]
    else:
        pool = [n for n in voices if re.sub(r"[^a-z]", "", want) in re.sub(r"[^a-z]", "", n.lower())]
    if cur in pool and want in ("male", "female"):
        return cur
    same = [n for n in pool if gender(n) == gender(cur)]
    return (same or pool or [None])[0]
