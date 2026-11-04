"""Reminders: saved in data/reminders.json, announced by notification and voice."""
import json
import os
import shutil
import subprocess
import threading
import time
from datetime import datetime, timedelta

from ..core import config

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


def add(task, when, every=None):
    item = {"text": task, "due": when.isoformat(), "done": False}
    if every:
        item["every"] = int(every)
    with _lock:
        items = _load()
        items.append(item)
        _save(items)


def pending():
    with _lock:
        items = [r for r in _load() if not r.get("done")]
    return sorted(items, key=lambda r: r["due"])


def clear():
    with _lock:
        _save([r for r in _load() if r.get("done")])


def cancel(words):
    """Stop the pending reminders whose text contains all of words. Returns how many."""
    words = [w for w in str(words).lower().split() if w]
    n = 0
    with _lock:
        items = _load()
        for r in items:
            text = r["text"].lower()
            if not r.get("done") and words and all(w in text for w in words):
                r["done"] = True
                n += 1
        if n:
            _save(items)
    return n


def take_due(now=None):
    now = now or datetime.now()
    due = []
    with _lock:
        items = _load()
        for r in items:
            if r.get("done") or datetime.fromisoformat(r["due"]) > now:
                continue
            due.append(r["text"])
            every = r.get("every")
            if every:
                # skip the slots missed while the laptop slept, so it fires once and not in a burst
                nxt = datetime.fromisoformat(r["due"])
                while nxt <= now:
                    nxt += timedelta(seconds=every)
                r["due"] = nxt.isoformat()
            else:
                r["done"] = True
        if due:
            _save(items)
    return due


def friendly(dt):
    delta = (dt.date() - datetime.now().date()).days
    day = "today" if delta == 0 else "tomorrow" if delta == 1 else dt.strftime("%A %d %B")
    return f"{day} at {dt.strftime('%I:%M %p').lstrip('0')}"


def interval(seconds):
    for unit, size in (("hour", 3600), ("minute", 60)):
        if seconds >= size and seconds % size == 0:
            n = seconds // size
            return f"every {unit}" if n == 1 else f"every {n} {unit}s"
    return f"every {seconds} seconds"


def describe():
    items = pending()
    if not items:
        return "You have no pending reminders."
    parts = [f"{r['text']}, " + (interval(r["every"]) + ", next " if r.get("every") else "")
             + friendly(datetime.fromisoformat(r["due"])) for r in items]
    n = len(items)
    return f"You have {n} reminder{'s' if n > 1 else ''}. " + ". ".join(parts) + "."


def notify(text):
    from ..voice import voice
    print(f"\n*** REMINDER: {text} ***")
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "-u", "critical", "Reminder", text])
    pet = config.PET_NAME or "Hey"
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
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        print(describe())
        sys.exit(0)
    from ..voice import voice
    add("this is a test reminder", datetime.now() + timedelta(seconds=20))
    print("test reminder set for 20 seconds from now, waiting")
    watch(notify)
    time.sleep(24)
    voice.wait()
