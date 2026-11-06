"""Checks adaptive reminders, quiet hours and snooze parsing in a scratch folder. Run: python scripts/reminders_check.py"""
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-reminders-"))
os.environ["JARVIS_DATA"] = str(tmp)

from jarvis.actions import reminder_tools, tools  # noqa: E402,F401
from jarvis.core import main as core  # noqa: E402
from jarvis.memory import store  # noqa: E402
from jarvis.scheduling import reminders  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def backdate(seconds):
    old = (datetime.now() - timedelta(seconds=seconds)).isoformat(timespec="seconds")
    with store.db() as con:
        con.execute("UPDATE reminder_events SET ts=? WHERE id=(SELECT MAX(id) FROM reminder_events)", (old,))


def fire_now(text, **kw):
    reminders.add(text, datetime.now() - timedelta(seconds=1), **kw)
    spoken = []
    for item in reminders.take_due_items():
        reminders.fire(item, spoken.append)
    return spoken


# the old file format still loads
reminders.FILE.write_text(json.dumps([{"text": "old one", "due": (datetime.now() + timedelta(hours=1)).isoformat(), "done": False}]))
check("old reminders.json loads", reminders.pending()[0]["text"] == "old one")
reminders._save([])

# snoozing three times asks about a better time
for target in ("21:00", "21:30", "21:40"):
    fire_now("take medicine")
    h, m = map(int, target.split(":"))
    when = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0) + timedelta(days=1)
    got = reminders.snooze(when)
check("third snooze returns a suggested time", got[1] == 3 and got[2] == "21:30")
fire_now("take medicine")
check("the move question is asked only once", reminders.snooze(datetime.now() + timedelta(hours=1))[2] is None)
moved = reminders.move("take medicine", "21:30")
check("move sets the new time of day", moved.strftime("%H:%M") == "21:30")

# tools
fire_now("stretch")
with mock.patch.object(reminders, "add"):
    line = tools.TOOLS["snooze_reminder"]["fn"]({"for": "20 minutes"})
check("snooze tool speaks the new time", "stretch" in line)
check("snooze phrases", all(reminder_tools.snooze_time(p) for p in ("10 minutes", "twenty minutes", "tonight", "half an hour", "tomorrow morning", "")))
check("tonight is 21:00", reminder_tools.snooze_time("tonight").hour == 21)

# ignored twice, then escalation
for _ in range(2):
    fire_now("drink water")
    backdate(400)
    reminders.sweep(lambda t: None)
check("two ignored in a row are counted", reminders.consecutive_ignored("drink water") == 2)
spoken = fire_now("drink water")
check("first announcement is normal", len(spoken) == 1)
with mock.patch.object(reminders, "_sound") as sound:
    base = time.time()
    reminders.sweep(spoken.append, now=base + 100)
    check("no repeat before ten minutes", len(spoken) == 1)
    reminders.sweep(spoken.append, now=base + 650)
    reminders.sweep(spoken.append, now=base + 1300)
    check("repeats every ten minutes", len(spoken) == 3 and not sound.called)
    reminders.sweep(spoken.append, now=base + 1950)
    check("third repeat comes with sound", len(spoken) == 4 and sound.called)
fire_now("drink water")
got = reminders.acknowledge()
check("an answer stops the escalation", got and not reminders._escalating)

# quick acknowledgement five times stops a repeating reminder
reminders.add("posture check", datetime.now() + timedelta(hours=2), every=3600)
for _ in range(5):
    with reminders._lock:
        items = reminders._load()
        for r in items:
            if r["text"] == "posture check":
                r["due"] = (datetime.now() - timedelta(seconds=1)).isoformat()
        reminders._save(items)
    for item in reminders.take_due_items():
        reminders.fire(item, lambda t: None)
    got = reminders.acknowledge()
check("fast acknowledgements end the repeat", "stopped repeating" in got[2] and not [r for r in reminders.pending() if r["text"] == "posture check"])

# stop repeating this one
reminders.add("water", datetime.now() + timedelta(hours=2), every=1800)
with reminders._lock:
    items = reminders._load()
    items[-1]["due"] = (datetime.now() - timedelta(seconds=1)).isoformat()
    reminders._save(items)
for item in reminders.take_due_items():
    reminders.fire(item, lambda t: None)
check("stop repeating works", reminders.stop_repeating() == "water" and not any(r["text"] == "water" for r in reminders.pending()))

# quiet hours
late = datetime.now().replace(hour=23, minute=30)
reminders._save([])
reminders.add("sleepy chore", late - timedelta(minutes=5))
reminders.add("urgent: call back", late - timedelta(minutes=5))
quiet = {"QUIET_START": "23:00", "QUIET_END": "07:00"}
with mock.patch.object(reminders.config, "get", side_effect=lambda n, d="": quiet.get(n, d)):
    got = [r["text"] for r in reminders.take_due_items(late)]
    check("quiet hours hold normal reminders", got == ["urgent: call back"])
    morning = late.replace(hour=7, minute=1) + timedelta(days=1)
    check("held reminders fire after quiet hours", [r["text"] for r in reminders.take_due_items(morning)] == ["sleepy chore"])

# focus mode holds non-urgent reminders
reminders.add("focus chore", datetime.now() - timedelta(seconds=1))
with mock.patch.object(reminders.state, "get", return_value=time.time() + 600):
    noon = datetime.now().replace(hour=12, minute=0)
    check("focus mode holds reminders", reminders.take_due_items(noon) == [])

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
