"""Which language Jarvis listens for and answers in. Hindi and Kannada are told apart by script."""
import json
import re

from . import config

CODES = {"hindi": "hi", "kannada": "kn", "english": "en", "hi": "hi", "kn": "kn", "en": "en"}
NAMES = {"hi": "Hindi", "kn": "Kannada", "en": "English"}
RANGES = {"hi": re.compile("[ऀ-ॿ]"), "kn": re.compile("[ಀ-೿]")}
ALLOWED = ("en", "hi", "kn")
_session = {"listen": None, "reply": None, "loaded": False}
CONFIRM = {"en": "Okay, I will reply in English.", "hi": "ठीक है, अब मैं हिंदी में जवाब दूँगा।", "kn": "ಸರಿ, ಇನ್ನು ಮುಂದೆ ಕನ್ನಡದಲ್ಲಿ ಉತ್ತರಿಸುತ್ತೇನೆ."}
CONFIRM_AUTO = "Okay, I will reply in English unless you write in Hindi or Kannada."


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


def _file():
    return config.DATA / "settings.json"


def _read():
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def reply_setting():
    """The reply language the user set ('en', 'hi' or 'kn'), or None for automatic. It lives in data/settings.json under "language" and survives a restart;
    nothing else (not a Hindi test, not an earlier message) can leave it on."""
    if not _session["loaded"]:
        saved = (_read().get("language") or {}).get("reply") if isinstance(_read().get("language"), dict) else None
        _session["reply"] = saved if saved in ALLOWED else None
        _session["loaded"] = True
    return _session["reply"]


def set_reply(name):
    """Set the reply language ('english', 'hindi', 'kannada') or go back to automatic ('auto'), and save it."""
    _session["reply"] = code(name) or None
    _session["loaded"] = True
    data = _read()
    block = data.get("language") if isinstance(data.get("language"), dict) else {}
    if _session["reply"]:
        block["reply"] = _session["reply"]
    else:
        block.pop("reply", None)
    data["language"] = block
    try:
        from . import jsonfile
        jsonfile.write(_file(), data)
    except OSError:
        pass


def reply_language(text=""):
    """The language of the next reply: the one the user set, else the language of the current message (English for anything in Latin letters)."""
    return reply_setting() or script(text)


def label():
    """For the status pill and Settings: 'English (auto)', 'English', 'Hindi' or 'Kannada'."""
    setting = reply_setting()
    return NAMES[setting] if setting else "English (auto)"


def confirmation(name):
    c = code(name)
    return CONFIRM.get(c, CONFIRM_AUTO)


def reply_hint(text):
    """The line that fixes the reply language, for every prompt: 'Reply in English only, short.' (or Hindi, or Kannada)."""
    return f"Reply in {NAMES[reply_language(text)]} only, short."
