"""Which Piper voice is in use. The choice is saved in data/settings.json and applies on the next spoken reply."""
import json
import re
from pathlib import Path

from ..core import config, lang

DEFAULT = "en_US-ryan-medium"
DIRS = (config.MODELS / "voices", Path.home() / "piper-voices")
MALE = ("ryan", "joe", "alan", "northern_english_male", "arctic", "danny", "kusal", "john", "bryce", "pratham", "jarvis")
ACCENTS = {"en_GB": "a British", "en_US": "an American", "hi_IN": "a Hindi"}
HINDI = "hi_IN-pratham-medium"
SETTINGS = config.DATA / "settings.json"


def installed():
    """{voice name: path to its .onnx} for every voice that has its .json next to it."""
    found = {}
    for d in DIRS:
        for p in sorted(d.glob("*.onnx")):
            if p.with_name(p.name + ".json").exists():
                found.setdefault(p.stem, p)
    return found


def english():
    """The voices that speak English; the film voice jarvis counts as one."""
    return [n for n in installed() if n.startswith("en_") or n == "jarvis"]


def for_language(code):
    """Path to an installed voice for 'hi' or 'kn', or None when there is none (no Kannada voice ships yet)."""
    voices = installed()
    names = [n for n in voices if n.startswith(code + "_")]
    return voices[HINDI if HINDI in names and code == "hi" else names[0]] if names else None


def path_for(text):
    """The voice that should read this text: the language voice for Devanagari or Kannada script, else the chosen one."""
    code = lang.script(text)
    return (for_language(code) if code != "en" else None) or current_path()


def gender(name):
    return "male" if any(m in name.lower() for m in MALE) else "female"


def label(name):
    """A speakable name such as 'Ryan, an American male voice'."""
    if "-" not in name:
        return f"the {name.replace('_', ' ').title()} voice"
    who = name.split("-")[1].replace("_", " ").title()
    return f"{who}, {ACCENTS.get(name[:5], 'a')} {gender(name)} voice"


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
    return next(iter(english()), first_run_default())


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
    names = english()
    if not names:
        return None
    cur = current_name()
    return names[(names.index(cur) + 1) % len(names)] if cur in names else names[0]


def find(want):
    """The best installed voice for 'male', 'female', 'british' or part of a voice name."""
    voices = english()
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
