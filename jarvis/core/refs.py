"""What "it", "that" and "this" mean: the last model, file or project that Jarvis built or opened. Held in memory for the session."""
import time

KINDS = ("model", "file", "project")
MAX_AGE = 3600
_last = {}


def remember(kind, name, path=None):
    _last[kind] = {"kind": kind, "name": str(name), "path": str(path) if path else "", "at": time.time()}


def latest(kinds=KINDS, now=None):
    """The newest reference of the given kinds from the last hour, or None."""
    now = now or time.time()
    found = [r for k, r in _last.items() if k in kinds and now - r["at"] <= MAX_AGE]
    return max(found, key=lambda r: r["at"]) if found else None


def forget():
    _last.clear()
