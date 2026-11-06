"""Small shared state file so the window, the daemon and the assistant can talk to each other."""
import json
import os
import threading
import time
from pathlib import Path

_base = Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state"))
PATH = _base / "jarvis" / "state.json"
DEFAULTS = {"muted": False, "paused": False, "talk_request": 0.0,
            "activity": "idle", "activity_at": 0.0, "focus_until": 0.0, "break_until": 0.0, "guard": None}
_cache = {"t": 0.0, "data": dict(DEFAULTS)}


def read():
    now = time.time()
    if now - _cache["t"] < 0.3:
        return _cache["data"]
    merged = dict(DEFAULTS)
    try:
        data = json.loads(PATH.read_text())
        if isinstance(data, dict):
            for key in DEFAULTS:
                if key in data:
                    merged[key] = data[key]
    except (OSError, ValueError):
        pass
    _cache["t"] = now
    _cache["data"] = merged
    return merged


def get(key):
    return read()[key]


def update(**changes):
    data = dict(read())
    data.update(changes)
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_name(f"{PATH.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, PATH)
    _cache["t"] = 0.0
