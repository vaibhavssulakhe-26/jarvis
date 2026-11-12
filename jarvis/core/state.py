"""Small shared state file so the window, the daemon and the assistant can talk to each other."""
import time

from .. import platform
from . import config, jsonfile

PATH = platform.state_dir() / config.PROFILE / "state.json"
DEFAULTS = {"muted": False, "paused": False, "talk_request": 0.0,
            "activity": "idle", "activity_at": 0.0, "focus_until": 0.0, "break_until": 0.0, "guard": None,
            "clipwatch": None, "command": "", "command_at": 0.0,
            "proactive": None, "quiet_until": 0.0, "touched_at": 0.0, "stop_at": 0.0, "pomodoro": None, "dictating": False, "theme_at": 0.0}
_cache = {"t": 0.0, "data": dict(DEFAULTS)}


def read():
    now = time.time()
    if now - _cache["t"] < 0.3:
        return _cache["data"]
    merged = dict(DEFAULTS)
    data = jsonfile.read(PATH, {}, dict)
    merged.update({key: data[key] for key in DEFAULTS if key in data})
    _cache["t"] = now
    _cache["data"] = merged
    return merged


def get(key):
    return read()[key]


def update(**changes):
    data = dict(read())
    data.update(changes)
    jsonfile.write(PATH, data)
    _cache["t"] = 0.0
