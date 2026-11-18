"""Timetable, deadlines and the daily brief, with no network and no microphone. Run: python scripts/timetable_check.py"""
import os
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-timetable-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CALENDAR_ICS_URL", "BRAIN"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import alerts, tasks, timetable  # noqa: E402
from jarvis.actions import tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.routines import morning, runner  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []

# the whole check runs on a fixed clock: Wednesday 18 November 2026, 10:00
NOW = datetime(2026, 11, 18, 10, 0)


class FixedDate(date):
    @classmethod
    def today(cls):
        return NOW.date()


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW


import datetime as _dt  # noqa: E402

for _mod in [m for n, m in list(sys.modules.items()) if n.startswith("jarvis") and m]:
    for _name, _real, _fake in (("date", _dt.date, FixedDate), ("datetime", _dt.datetime, FixedDateTime)):
        if getattr(_mod, _name, None) is _real:
            setattr(_mod, _name, _fake)


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def said(text):
    """What a typed command would have said."""
    with voice.capture() as lines:
        core.direct(text) or core.fast_path(text)
    return " ".join(lines)


today = date(2026, 11, 18)  # a Wednesday
check("parse weekday", timetable.parse_date("friday", today) == date(2026, 11, 20))
check("parse next same weekday", timetable.parse_date("next wednesday", today) == date(2026, 11, 25))
check("parse day and month", timetable.parse_date("on 5 December", today) == date(2026, 12, 5))
check("parse month first", timetable.parse_date("march 3rd", today) == date(2027, 3, 3))
check("parse slash date", timetable.parse_date("20/11", today) == date(2026, 11, 20))
check("parse tomorrow and in days", timetable.parse_date("tomorrow", today) == date(2026, 11, 19) and timetable.parse_date("in 2 weeks", today) == date(2026, 12, 2))
check("unclear date is None", timetable.parse_date("whenever", today) is None)
check("countdown words", [timetable.countdown(today + timedelta(days=n), today) for n in (0, 1, 3, -2)] == ["today", "tomorrow", "in 3 days", "2 days ago"])
check("class parse", timetable.parse_class("monday 9 to 10 data structures room 204") == (0, "09:00", "10:00", "Data Structures", "Room 204"))
check("class parse pm", timetable.parse_class("on tuesday from 2 pm to 3:30 pm maths in lab 3")[1:3] == ("14:00", "15:30"))
check("class parse bare afternoon hour", timetable.parse_class("friday 2 to 4 networks")[1:3] == ("14:00", "16:00"))
check("class without a day asks", isinstance(timetable.parse_class("9 to 10 physics"), str))

# the real weekday of today gets a class so the tools (which read the clock) have something to say
wd = today.weekday()
name = timetable.DAYS[wd].title()
other = timetable.DAYS[(wd + 2) % 7].title()
with voice.capture() as out:
    core.direct(f"add class {name} 00:01 to 23:50 algorithms room 12") or core.direct(f"add class {name} 12 am to 11:50 pm algorithms room 12")
check("add class by voice", any("Added" in x for x in out) or timetable.classes(), str(out))
if not timetable.classes():
    timetable.add_class(wd, "00:01", "23:50", "Algorithms", "Room 12")
timetable.add_class((wd + 2) % 7, "09:00", "10:00", "Operating Systems", "Lab 3")
check("timetable file is plain text", "Algorithms" in (tmp / "timetable.md").read_text() and "|" in (tmp / "timetable.md").read_text())
(tmp / "timetable.md").write_text((tmp / "timetable.md").read_text() + "\nrandom line the parser must skip\n- Funday 09:00-10:00 | Nope\n")
check("bad lines are skipped", len(timetable.classes()) == 2)

mon = datetime(2026, 11, 16, 8, 0)
timetable.add_class(0, "09:00", "10:00", "Data Structures", "Room 204")
got = timetable.next_class(mon)
check("next class from the model clock", got and got[0]["subject"] == "Data Structures" and got[1] == date(2026, 11, 16))
check("next class rolls to the next day when today is over", timetable.next_class(datetime(2026, 11, 16, 23, 0))[1] > date(2026, 11, 16))

check("direct: next class", "next class" in said("next class").lower() or "class" in said("what is my next class").lower())
check("direct: today's schedule", "Algorithms" in said("what's today's schedule"), said("what's today's schedule"))
check("direct: what's due is empty at first", "No deadlines" in said("what's due this week"))
reply = said("add deadline DSA assignment on friday")
check("add deadline by voice", "Saved" in reply and (tmp / "deadlines.md").exists(), reply)
tomorrow = today + timedelta(days=1)
reply = said(f"add deadline lab report on {tomorrow.day} {timetable.MONTHS[tomorrow.month - 1]}")
check("deadline with a date in words", "tomorrow" in reply, reply)
check("add deadline without a date asks", "Which date" in said("add deadline something on whenever"))
due = said("what's due this week")
check("what's due lists them", "lab report" in due and "deadline" in due, due)
check("deadlines file is plain text", "lab report" in (tmp / "deadlines.md").read_text())

# tasks
check("task: shorthand", "saved" in said("task: buy a cable").lower())
said("add task email the dean")
check("list tasks", "2 open tasks" in said("list tasks"), said("list tasks"))
check("done by number", "buy a cable" in said("done 1"))
check("done out of range", "1 open task" in said("done 7"))
check("clear done", "Cleared 1" in said("clear done"))
check("tasks file has the date", today.isoformat() in (tmp / "tasks.md").read_text())

# the brief
captured = {}


def fake_ask(prompt, tokens, system=None, **kw):
    captured.update(prompt=prompt, tokens=tokens, system=system, calls=captured.get("calls", 0) + 1)
    return "Algorithms is your main class. Your DSA assignment is due soon. Start with the assignment."


with mock.patch.object(brain, "ask", fake_ask):
    result = morning.build(NOW)
total = brain.estimate([{"role": "system", "content": captured["system"]}, {"role": "user", "content": captured["prompt"]}]) + captured["tokens"]
check("one brain call for the whole brief", captured["calls"] == 1)
check("brief stays under 800 tokens in and out", total < 800, str(total))
check("prompt carries classes, deadlines and tasks", all(w in captured["prompt"] for w in ("Algorithms", "DSA assignment", "email the dean")))
check("brief note has the new sections", all(h in result["text"] for h in ("## Classes", "## Deadlines", "## Tasks")))
check("spoken brief is at most three sentences", len(morning.sentences(result["spoken"])) <= 3)

with mock.patch.object(brain, "ask", side_effect=RuntimeError("no brain")):
    plain = morning.build(NOW)
check("no brain gives a template", plain["source"] == "template" and "Algorithms" in plain["spoken"] or "Due soon" in plain["spoken"], plain["spoken"])
check("template names a focus", "Focus on" in plain["spoken"] or "Next up" in plain["spoken"], plain["spoken"])
check("template is at most three sentences", len(morning.sentences(plain["spoken"])) <= 3, plain["spoken"])

# pushing the brief: dashboard line, voice, phone, once a day
shown, spoken, phone = [], [], []
from jarvis.actions import events  # noqa: E402
events.listeners.append(lambda kind, text: shown.append((kind, text)))
with mock.patch("jarvis.telegram.notify_once", lambda key, text: phone.append(text) or True), mock.patch.object(runner.reminders, "in_quiet", lambda n: False):
    runner.push(spoken.append)
    runner.push(spoken.append)
check("push shows the brief on the dashboard once", sum(1 for k, t in shown if k == "sys" and t.startswith("# Briefing")) == 1)
check("push sends it to the phone", len(phone) >= 1 and phone[0].startswith("# Briefing"))
check("push speaks at most three sentences", spoken and len(morning.sentences(spoken[0])) <= 3)

# a failing briefing is an alert
with mock.patch.object(morning, "build", side_effect=ValueError("boom")):
    ok, line = __import__("jarvis.routines", fromlist=["x"]).run_one({"time": "08:00", "name": "morning briefing", "instruction": "x", "action": "briefing"})
check("a failing routine is reported", not ok and alerts.count() == 1 and "morning briefing" in alerts.read()[0]["source"])

print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}")
sys.exit(1 if bad else 0)
