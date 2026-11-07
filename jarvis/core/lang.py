"""Which language Jarvis listens for and answers in. Hindi and Kannada are told apart by script."""
import re

from . import config

CODES = {"hindi": "hi", "kannada": "kn", "english": "en", "hi": "hi", "kn": "kn", "en": "en"}
NAMES = {"hi": "Hindi", "kn": "Kannada", "en": "English"}
RANGES = {"hi": re.compile("[ऀ-ॿ]"), "kn": re.compile("[ಀ-೿]")}
ALLOWED = ("en", "hi", "kn")
_session = {"listen": None, "reply": None}


def code(name):
    """'hi', 'kn' or 'en' for a language name, '' for auto or anything unknown."""
    return CODES.get(str(name or "").strip().lower(), "")


def script(text):
    """'hi' or 'kn' when the text is mostly in that script, else 'en'."""
    best, most = "en", 1
    for lang, rx in RANGES.items():
        n = len(rx.findall(str(text)))
        if n > most:
            best, most = lang, n
    return best


def listening():
    """The speech-to-text language: set by voice for this session, else STT_LANGUAGE (English unless changed); '' means auto."""
    return code(config.get("STT_LANGUAGE") or "en") if _session["listen"] is None else _session["listen"]


def allowed(detected):
    """True when an auto-detected language is one Jarvis works in (English, Hindi or Kannada). Unknown counts as fine."""
    return not detected or code(detected) in ALLOWED


def set_listening(name):
    _session["listen"] = code(name)


def set_reply(name):
    _session["reply"] = code(name) or None


def reply_hint(text):
    """One short line telling the brain which language to answer in: English, Hindi or Kannada, never another."""
    lang = _session["reply"] or script(text)
    if lang == "en" and not _session["reply"]:
        return "Reply only in English, Hindi or Kannada."
    return f"Answer in {NAMES[lang]}" + (", short spoken style." if lang != "en" else ".")
