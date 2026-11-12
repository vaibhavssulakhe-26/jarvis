"""Reminders: saved in data/reminders.json, announced by notification and voice.
What the user does about each one (acknowledge, snooze, ignore) is logged in the database and shapes later reminders."""
import re
import statistics
import subprocess
import threading
import time
from datetime import datetime, timedelta

from .. import platform
from ..core import config, jsonfile, state
from ..memory import store

FILE = config.DATA / "reminders.json"
_lock = threading.Lock()
ACK_WINDOW = 300
FAST_ACK = 60
ESCALATE_EVERY = 600
ESCALATE_TIMES = 3
SNOOZE_LIMIT = 3
HABIT_RUN = 5
_escalating = {}


def _load():
    return jsonfile.read(FILE, [], list)


def _save(items):
    jsonfile.write(FILE, items, indent=2)


def add(task, when, every=None, urgent=False):
    item = {"text": task, "due": when.isoformat(), "done": False}
    if every:
        item["every"] = int(every)
    if urgent:
        item["urgent"] = True
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


def _hm(raw):
    m = re.fullmatch(r"(\d{1,2}):(\d{2})", str(raw or "").strip())
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def in_quiet(now):
    start, end = _hm(config.get("QUIET_START")), _hm(config.get("QUIET_END"))
    if start is None or end is None or start == end:
        return False
    t = now.hour * 60 + now.minute
    return start <= t < end if start < end else (t >= start or t < end)


def held(item, now):
    """Non-urgent reminders wait out quiet hours and focus mode."""
    if item.get("urgent") or re.search(r"\b(urgent|important)\b", item["text"], re.I):
        return False
    return in_quiet(now) or float(state.get("focus_until") or 0) > now.timestamp()


def take_due_items(now=None):
    now = now or datetime.now()
    due = []
    with _lock:
        items = _load()
        for r in items:
            if r.get("done") or datetime.fromisoformat(r["due"]) > now or held(r, now):
                continue
            due.append(dict(r))
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


# ---------- what the user did about each reminder ----------
def _stamp(dt=None):
    return (dt or datetime.now()).isoformat(timespec="seconds")


def record_fire(item):
    with store.db() as con:
        return con.execute("INSERT INTO reminder_events(ts, text, outcome, due, acted) VALUES(?,?,?,?,?)",
                           (_stamp(), item["text"], "fired", item.get("due", ""), "")).lastrowid


def _recent_outcomes(text, n=5):
    with store.db() as con:
        rows = con.execute("SELECT outcome FROM reminder_events WHERE lower(text)=? AND outcome!='fired' "
                           "ORDER BY id DESC LIMIT ?", (text.lower(), n)).fetchall()
    return [r["outcome"] for r in rows]


def consecutive_ignored(text):
    n = 0
    for outcome in _recent_outcomes(text):
        if outcome != "ignored":
            break
        n += 1
    return n


def active(max_age=1800):
    """The latest reminder that fired and was not dealt with yet, as a dict, or None."""
    cutoff = _stamp(datetime.now() - timedelta(seconds=max_age))
    with store.db() as con:
        row = con.execute("SELECT * FROM reminder_events WHERE outcome IN ('fired','ignored') AND ts>=? "
                          "ORDER BY id DESC LIMIT 1", (cutoff,)).fetchone()
    return dict(row) if row else None


def _resolve(row, outcome, acted=None):
    with store.db() as con:
        con.execute("UPDATE reminder_events SET outcome=?, acted=? WHERE id=?",
                    (outcome, acted or _stamp(), row["id"]))
    _escalating.pop(row["id"], None)


def _pending_item(text, repeating=False):
    for r in pending():
        if r["text"].lower() == text.lower() and (r.get("every") or not repeating):
            return r
    return None


def _drop_repeat(text):
    with _lock:
        items = _load()
        for r in items:
            if r["text"].lower() == text.lower() and not r.get("done") and r.get("every"):
                r["done"] = True
        _save(items)


def acknowledge():
    """The user said they have seen it. Returns (text, outcome, extra sentence) or None."""
    row = active()
    if not row:
        return None
    seconds = (datetime.now() - datetime.fromisoformat(row["ts"])).total_seconds()
    outcome = "acked_fast" if seconds <= FAST_ACK else "acked"
    _resolve(row, outcome)
    extra = ""
    recent = _recent_outcomes(row["text"], HABIT_RUN)
    if len(recent) >= HABIT_RUN and set(recent) == {"acked_fast"} and _pending_item(row["text"], True):
        _drop_repeat(row["text"])
        extra = (f"You deal with {row['text']} straight away every time, so I stopped repeating it. "
                 "Ask me again if you want it back.")
    return row["text"], outcome, extra


def snooze(when):
    """Move the active reminder to a new time. Returns (text, snooze count, suggested HH:MM or None)."""
    row = active()
    if not row:
        return None
    _resolve(row, "snoozed", _stamp(when))
    add(row["text"], when)
    with store.db() as con:
        count = con.execute("SELECT COUNT(*) AS n FROM reminder_events WHERE lower(text)=? AND outcome='snoozed' "
                            "AND ts>=?", (row["text"].lower(), _stamp(datetime.now() - timedelta(days=14)))).fetchone()["n"]
    suggestion = None
    if count >= SNOOZE_LIMIT and store.claim("moveasked:" + row["text"].lower(), "yes"):
        suggestion = median_time(row["text"])
    return row["text"], count, suggestion


def median_time(text):
    """The time of day the user usually acts on a reminder, as HH:MM, or None without enough history."""
    with store.db() as con:
        rows = con.execute("SELECT acted FROM reminder_events WHERE lower(text)=? AND outcome IN "
                           "('acked','acked_fast','snoozed') AND acted!='' ORDER BY id DESC LIMIT 12",
                           (text.lower(),)).fetchall()
    minutes = []
    for r in rows:
        try:
            t = datetime.fromisoformat(r["acted"])
            minutes.append(t.hour * 60 + t.minute)
        except ValueError:
            continue
    if len(minutes) < 2:
        return None
    mid = int(statistics.median(minutes))
    return f"{mid // 60:02d}:{mid % 60:02d}"


def move(text, hhmm):
    """Reschedule a reminder to the next HH:MM."""
    h, m = divmod(_hm(hhmm), 60)
    when = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
    if when <= datetime.now():
        when += timedelta(days=1)
    with _lock:
        items = _load()
        hit = next((r for r in items if not r.get("done") and r["text"].lower() == text.lower()), None)
        if hit:
            hit["due"] = when.isoformat()
            _save(items)
            return when
    add(text, when)
    return when


def stop_repeating():
    row = active()
    if not row or not _pending_item(row["text"], True):
        return None
    _drop_repeat(row["text"])
    _resolve(row, "acked")
    return row["text"]


def _sound():
    cmd = platform.alarm_sound()
    if cmd:
        subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sweep(on_due, now=None):
    """Mark unanswered reminders as ignored, and repeat the ones that were ignored twice before."""
    now = now or time.time()
    with store.db() as con:
        rows = [dict(r) for r in con.execute("SELECT * FROM reminder_events WHERE outcome='fired'")]
    for row in rows:
        age = now - datetime.fromisoformat(row["ts"]).timestamp()
        esc = _escalating.get(row["id"])
        if esc is None:
            if age > ACK_WINDOW:
                _resolve(row, "ignored", "")
            continue
        if now < esc["next"]:
            continue
        esc["left"] -= 1
        esc["next"] = now + ESCALATE_EVERY
        if esc["left"] <= 0:
            _sound()
            on_due(row["text"])
            _resolve(row, "ignored", "")
        else:
            on_due(row["text"])


def fire(item, on_due):
    """Announce one due reminder and log it. A reminder ignored twice in a row gets repeated."""
    escalate = consecutive_ignored(item["text"]) >= 2
    event = record_fire(item)
    if escalate:
        _escalating[event] = {"left": ESCALATE_TIMES, "next": time.time() + ESCALATE_EVERY}
    on_due(item["text"])


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
    platform.notify("Reminder", text, urgent=True)
    pet = config.PET_NAME or "Hey"
    voice.say(f"{pet}, reminder: {text}.")


def watch(on_due):
    """Check every second in the background and call on_due(text) for each due reminder."""
    def loop():
        last_sweep = 0.0
        while True:
            try:
                for item in take_due_items():
                    fire(item, on_due)
                if time.time() - last_sweep > 10:
                    last_sweep = time.time()
                    sweep(on_due)
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
