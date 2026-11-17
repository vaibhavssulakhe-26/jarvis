"""Failures of routines, the briefing and other scheduled jobs. Each one is a line in data/alerts.jsonl, a chip on the dashboard and,
when the phone is paired, a Telegram message (the same alert at most once an hour). Text is masked before it is stored."""
import json
import threading
import time
from datetime import datetime

import requests

from . import redact
from .core import config

KEEP = 200
REPEAT_SECONDS = 3600
_lock = threading.Lock()
_sent = {}


def path():
    return config.DATA / "alerts.jsonl"


def describe(exc):
    """A short line for an exception. Network errors give only the type: their text can hold a URL with a token in it."""
    name = type(exc).__name__
    if isinstance(exc, requests.RequestException) or not str(exc):
        return name
    return f"{name}: {redact.mask(str(exc))[:100]}"


_seen = {}


def add(source, message, quiet_for=0):
    """Record an alert and tell the dashboard and the phone. Never raises. With `quiet_for` seconds, the same alert from a loop that fails
    again and again is recorded only once in that time."""
    try:
        if quiet_for:
            if time.time() - _seen.get((source, message), 0) < quiet_for:
                return
            _seen[(source, message)] = time.time()
        entry = {"at": datetime.now().isoformat(timespec="seconds"), "source": str(source)[:40], "message": redact.mask(message)[:200]}
        with _lock:
            rows = read()[-(KEEP - 1):] + [entry]
            path().parent.mkdir(parents=True, exist_ok=True)
            path().write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        print(f"  (alert: {entry['source']}: {entry['message']})")
        from .actions import events
        events.emit("alert", f"{entry['source']}: {entry['message']}")
        key = (entry["source"], entry["message"])
        if time.time() - _sent.get(key, 0) > REPEAT_SECONDS:
            _sent[key] = time.time()
            from . import telegram
            telegram.notify(f"Alert from {entry['source']}: {entry['message']}")
    except Exception as e:
        print(f"  (could not record an alert: {type(e).__name__})")


def read():
    out = []
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and "message" in row:
            out.append(row)
    return out


def count():
    return len(read())


def clear():
    n = count()
    try:
        path().unlink()
    except OSError:
        pass
    _sent.clear()
    return n


def lines(n=5):
    return [f"{r['at'][5:16].replace('T', ' ')}  {r.get('source', '')}: {r['message']}" for r in read()[-n:]][::-1]
