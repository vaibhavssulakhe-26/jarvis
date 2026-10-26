"""Reminders: saved in data/reminders.json, announced by notification and voice."""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime

from . import config

FILE = config.DATA / "reminders.json"
_lock = threading.Lock()


def _load():
    try:
        data = json.loads(FILE.read_text())
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save(items):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(FILE.name + ".tmp")
    tmp.write_text(json.dumps(items, indent=2))
    os.replace(tmp, FILE)


def add(task, when):
    with _lock:
        items = _load()
        items.append({"text": task, "due": when.isoformat(), "done": False})
        _save(items)


def pending():
    with _lock:
        items = [r for r in _load() if not r.get("done")]
    return sorted(items, key=lambda r: r["due"])


def clear():
    with _lock:
        _save([r for r in _load() if r.get("done")])


def take_due(now=None):
    now = now or datetime.now()
    due = []
    with _lock:
        items = _load()
        for r in items:
            if not r.get("done") and datetime.fromisoformat(r["due"]) <= now:
                r["done"] = True
                due.append(r["text"])
        if due:
            _save(items)
    return due


def friendly(dt):
    delta = (dt.date() - datetime.now().date()).days
    day = "today" if delta == 0 else "tomorrow" if delta == 1 else dt.strftime("%A %d %B")
    return f"{day} at {dt.strftime('%I:%M %p').lstrip('0')}"


def describe():
    items = pending()
    if not items:
        return "You have no pending reminders."
    parts = [f"{r['text']}, {friendly(datetime.fromisoformat(r['due']))}" for r in items]
    n = len(items)
    return f"You have {n} reminder{'s' if n > 1 else ''}. " + ". ".join(parts) + "."


def notify(text):
    from . import voice
    print(f"\n*** REMINDER: {text} ***")
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical", "Reminder", text])
    pet = config.get("USER_PET_NAME") or "Hey"
    voice.say(f"{pet}, reminder: {text}.")


def watch(on_due):
    """Check every second in the background and call on_due(text) for each due reminder."""
    def loop():
        while True:
            try:
                for text in take_due():
                    on_due(text)
            except Exception as e:
                print(f"  (reminder check failed: {type(e).__name__})")
            time.sleep(1)
    threading.Thread(target=loop, daemon=True).start()


if __name__ == "__main__":
    import sys
    from datetime import timedelta
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(describe())
        sys.exit(0)
    from . import voice
    add("this is a test reminder", datetime.now() + timedelta(seconds=20))
    print("test reminder set for 20 seconds from now, waiting")
    watch(notify)
    time.sleep(24)
    voice.wait()
