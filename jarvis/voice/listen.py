"""Listening modes. Crowd mode (CROWD_MODE, the Settings switch, or "crowd mode on") makes every command need the wake word, closes the
follow-up window and raises the speech threshold. The saved choice lives in data/settings.json and wins over .env."""
import time

from ..core import config
from . import voices

_cache = {"t": 0.0, "on": False}


def crowd():
    now = time.time()
    if now - _cache["t"] > 1.0:
        saved = voices.read_settings().get("crowd")
        _cache["on"] = bool(saved) if saved is not None else config.flag("CROWD_MODE")
        _cache["t"] = now
    return _cache["on"]


def set_crowd(on):
    data = voices.read_settings()
    data["crowd"] = bool(on)
    voices.write_settings(data)
    _cache["t"], _cache["on"] = time.time(), bool(on)


def suppress():
    return config.flag("NOISE_SUPPRESS")


def speech_threshold(floor, crowded):
    """Loudness that counts as speech, from the measured background."""
    if crowded:
        return min(0.3, max(0.03, 5.0 * floor))
    return min(0.25, max(0.015, 3.0 * floor))


def mode_label():
    return "crowd" if crowd() else "normal"
