"""Checks the pomodoro timer, the good morning line and quick notes. Fake clock, no audio, no network.
Run: python scripts/focus_check.py"""
import os
import sys
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from unittest import mock

scratch = Path(tempfile.mkdtemp(prefix="jarvis-focus-"))
os.environ["JARVIS_DATA"] = str(scratch)
os.environ["XDG_STATE_HOME"] = str(scratch)
os.environ["XDG_RUNTIME_DIR"] = str(scratch)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import focus_tools, study  # noqa: E402
from jarvis.core import main, state  # noqa: E402
from jarvis.scheduling import pomodoro, reminders  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


T = tools.TOOLS
spoken = []
speak = spoken.append
mock.patch.object(pomodoro, "watch", lambda: None).start()

check("no timer at first", pomodoro.status() is None and T["stop_focus"]["fn"]({}) == "No timer is running.")
out = T["start_focus"]["fn"]({"minutes": 25})
check("start focus 25 says so", out.startswith("Focus started for 25 minutes"), out)
cur = pomodoro.status()
check("the timer is in the state file for 25 minutes", cur["kind"] == "focus" and cur["minutes"] == 25 and abs(cur["until"] - cur["started"] - 1500) < 1)
check("reminders are held during focus", float(state.get("focus_until")) > time.time())
check("default length is 25", T["start_focus"]["fn"]({}).startswith("Focus started for 25 minutes"))
check("the length is capped", pomodoro.start("focus", 9999) == pomodoro.MAX_MINUTES)
try:
    T["start_focus"]["fn"]({"minutes": -5})
    check("a negative length is refused", False)
except tools.ToolError:
    check("a negative length is refused", True)

pomodoro.start("focus", 25)
t0 = pomodoro.status()["started"]
check("tick before the end does nothing", pomodoro.tick(speak, now=t0 + 600) is None and not spoken)
with mock.patch.object(pomodoro.time, "time", lambda: t0 + 600):
    check("time left is reported", "15 minutes left" in T["focus_left"]["fn"]({}))
done = pomodoro.tick(speak, now=t0 + 1501)
check("the end of focus is spoken once", done == "focus" and len(spoken) == 1 and "Focus session done" in spoken[0], str(spoken))
check("and the timer is cleared with the hold on reminders", pomodoro.status() is None and float(state.get("focus_until")) == 0.0)
check("25 minutes were credited to study", study.load()["days"][date.today().isoformat()]["study_min"] == 25)
check("tick after the end does not repeat", pomodoro.tick(speak, now=t0 + 1600) is None and len(spoken) == 1)

out = T["start_break"]["fn"]({})
check("break defaults to five minutes", "5 minutes" in out and pomodoro.status()["kind"] == "break", out)
check("a break does not hold reminders", float(state.get("focus_until")) == 0.0)
b0 = pomodoro.status()["started"]
pomodoro.tick(speak, now=b0 + 301)
check("the end of the break is spoken and not credited", "Break over" in spoken[-1] and study.load()["days"][date.today().isoformat()]["study_min"] == 25)

pomodoro.start("focus", 25)
f0 = pomodoro.status()["started"]
out = None
with mock.patch.object(pomodoro.time, "time", lambda: f0 + 12 * 60 + 5):
    out = T["stop_focus"]["fn"]({})
check("stop focus logs the minutes done so far", "12 minutes" in out, out)
check("the timer is gone after stop", pomodoro.status() is None and study.load()["days"][date.today().isoformat()]["study_min"] == 37)
pomodoro.start("focus", 25)
out = T["stop_focus"]["fn"]({})
check("stopping at once logs nothing", out == "Focus stopped.", out)
pomodoro.start("break", 5)
check("stop ends a break too", T["stop_focus"]["fn"]({}) == "Break stopped.")

state.update(pomodoro={"kind": "focus", "minutes": 25, "started": time.time() - 4000, "until": time.time() - 100}, focus_until=1.0)
pomodoro.resume()
n_spoken = len(spoken)
check("a timer that ran out while Jarvis was off is dropped quietly", pomodoro.status() is None and len(spoken) == n_spoken)

# do not disturb is opt in
calls = []
with mock.patch.object(pomodoro, "_call", lambda *a: calls.append(a) or mock.Mock(arguments=lambda: [7])):
    pomodoro.mute_notifications(True)
    check("notifications stay on unless FOCUS_MUTE_NOTIFICATIONS is set", not calls)
    with mock.patch.dict(os.environ, {"FOCUS_MUTE_NOTIFICATIONS": "true"}):
        check("opted in: focus inhibits notifications", pomodoro.mute_notifications(True) and calls[-1][1] == "Inhibit")
        check("only once while it is on", pomodoro.mute_notifications(True) is False and len(calls) == 1)
        check("and releases them afterwards", pomodoro.mute_notifications(False) and calls[-1][1] == "UnInhibit")
with mock.patch.object(pomodoro, "_call", side_effect=RuntimeError("no bus")), mock.patch.dict(os.environ, {"FOCUS_MUTE_NOTIFICATIONS": "true"}):
    check("a missing desktop service does not crash", pomodoro.mute_notifications(True) is False)

# good morning
reminders_today = ["call mom at 5:00 PM"]
with mock.patch.object(focus_tools, "_today_reminders", lambda: reminders_today):
    out = T["good_morning"]["fn"]({})
check("good morning gives the date and the reminder", datetime.now().strftime("%A") in out and "call mom" in out, out)
(scratch / "roadmap.md").write_text("- [x] Python\n- [ ] Binary trees\n")
data = study.load()
for i in range(1, 4):
    data["days"][(date.today() - __import__("datetime").timedelta(days=i)).isoformat()] = {"study_min": 30}
study.save(data)
with mock.patch.object(focus_tools, "_today_reminders", lambda: ["a", "b", "c"]):
    out = T["good_morning"]["fn"]({})
sentences = [s for s in out.split(". ") if s]
check("good morning is at most four sentences", len(sentences) <= 4, out)
check("it includes the roadmap item and the streak", "Binary trees" in out and "streak" in out and "3 reminders" in out, out)
with mock.patch.object(focus_tools, "_today_reminders", lambda: []):
    check("no reminders is said plainly", "no reminders" in T["good_morning"]["fn"]({}))
(scratch / "roadmap.md").unlink()
(scratch / "study.json").unlink()
with mock.patch.object(focus_tools, "_today_reminders", lambda: []):
    out = T["good_morning"]["fn"]({})
check("without a roadmap or streak it stays short", "roadmap" not in out and "streak" not in out, out)

# quick notes
notes_dir = focus_tools.notes.NOTES_DIR
with mock.patch.object(focus_tools.rag, "update_if_changed", lambda: (0, 0)):
    check("quick note says noted", T["quick_note"]["fn"]({"text": "buy a USB cable"}) == "Noted.")
    T["quick_note"]["fn"]({"text": "ask about\nthe lab"})
lines = (notes_dir / "inbox.md").read_text().splitlines()
check("notes are appended with a timestamp", lines[0] == "# Inbox" and lines[2].startswith("- [20") and lines[2].endswith("] buy a USB cable"), str(lines))
check("a note stays on one line", lines[3].endswith("ask about the lab") and len(lines) == 4)
try:
    T["quick_note"]["fn"]({"text": "  "})
    check("an empty note is refused", False)
except tools.ToolError:
    check("an empty note is refused", True)

# the real notes index sees the inbox
from jarvis.memory import rag  # noqa: E402
check("the inbox is inside the indexed notes folder", any(str(p).endswith("inbox.md") for p in rag.scan()))

# routing
ran = []
cases = (("start focus 25", "start_focus", {"minutes": 25}), ("start focus", "start_focus", {"minutes": ""}), ("start focus for 45 minutes", "start_focus", {"minutes": 45}),
         ("start focus twenty five", "start_focus", {"minutes": 25}), ("break", "start_break", {"minutes": ""}), ("take a break 10", "start_break", {"minutes": 10}),
         ("stop focus", "stop_focus", {}), ("good morning", "good_morning", {}), ("Good morning, Jarvis", "good_morning", {}),
         ("note: buy a cable", "quick_note", {"text": "buy a cable"}), ("Note, remember the form", "quick_note", {"text": "remember the form"}))
for phrase, name, args in cases:
    with mock.patch.object(main, "run_tool", lambda a, ar, s: ran.append((a, ar))), mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")):
        main.direct(phrase)
    check(f"{phrase!r} -> {name}", ran and ran[-1] == (name, args), str(ran[-1:]))
with mock.patch.object(main, "run_tool", lambda a, ar, s: ran.append((a, ar))):
    main.direct("I'm on a break")
check("'I'm on a break' still goes to the old break tool", ran[-1][0] == "take_break", str(ran[-1]))
sys.exit(1 if bad else 0)
