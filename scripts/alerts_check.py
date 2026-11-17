"""Alerts (failed routines and scheduled jobs) and quick tasks. No network. Run: python scripts/alerts_check.py"""
import json
import os
import sys
import tempfile
from datetime import date, datetime
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-alerts-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
for k in ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "CALENDAR_ICS_URL", "BRAIN"):
    os.environ.pop(k, None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import jarvis.routines as routines  # noqa: E402
from jarvis import alerts, tasks  # noqa: E402
from jarvis.actions import events  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.routines import morning, runner  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def said(text):
    with voice.capture() as lines:
        core.direct(text)
    return " ".join(lines)


sent, seen = [], []
events.listeners.append(lambda kind, text: seen.append((kind, text)))
patch = mock.patch("jarvis.telegram.notify", lambda text, wait=False: sent.append(text) or True)
patch.start()

check("no alerts at first", alerts.count() == 0 and "No alerts" in said("show alerts"))
alerts.add("nightly notes reindex", "routine failed: OSError: disk full for me@example.com")
check("an alert is a line in alerts.jsonl", len((tmp / "alerts.jsonl").read_text().splitlines()) == 1)
check("the text is masked", "me@example.com" not in (tmp / "alerts.jsonl").read_text())
check("the dashboard hears about it", any(k == "alert" for k, _ in seen))
check("the phone hears about it", len(sent) == 1 and "nightly notes reindex" in sent[0])
alerts.add("nightly notes reindex", "routine failed: OSError: disk full for me@example.com")
check("the same alert is not sent to the phone twice in an hour", len(sent) == 1 and alerts.count() == 2)
alerts.add("other job", "routine failed: ValueError")
check("a different alert is sent", len(sent) == 2)
check("show alerts reads them", "3 alerts" in said("show alerts"))
check("clear alerts empties the list", "Cleared 3" in said("clear alerts") and alerts.count() == 0)
check("an empty list says so", "No alerts" in said("show alerts"))

(tmp / "alerts.jsonl").write_text("not json\n" + json.dumps({"at": "2026-01-01T00:00:00", "source": "x", "message": "kept"}) + "\n")
check("a damaged line is skipped", alerts.count() == 1)
alerts.clear()
for i in range(alerts.KEEP + 20):
    alerts.add("flood", f"n{i}")
check("the file is capped", alerts.count() == alerts.KEEP)
alerts.clear()
err = requests.ConnectionError("HTTPSConnectionPool(host='api.example', token=SECRET123abcSECRET123abc)")
check("a network error is described by its type only", alerts.describe(err) == "ConnectionError")

# routines: a crash becomes an alert, a good run does not
good = {"time": "08:00", "name": "nightly notes reindex", "instruction": "reindex notes", "action": "reindex"}
with mock.patch("jarvis.memory.rag.reindex", side_effect=OSError("disk full")):
    ok, line = routines.run_one(good)
check("a failed routine writes an alert", not ok and alerts.count() == 1 and "OSError" in alerts.read()[0]["message"])
with mock.patch("jarvis.memory.rag.reindex", return_value=3):
    ok, line = routines.run_one(good)
check("a good routine writes none", ok and alerts.count() == 1)

# the runner loop itself
with mock.patch.object(routines, "run_due", side_effect=RuntimeError("loop broke")), mock.patch.object(runner, "run_due", side_effect=RuntimeError("loop broke")):
    import threading
    import time as _t
    real_sleep = _t.sleep
    calls = []

    def stop_sleep(n):
        calls.append(n)
        if len(calls) > 1:
            raise SystemExit
        return real_sleep(0)
    with mock.patch.object(runner.time, "sleep", stop_sleep):
        try:
            runner.start(lambda t: None, first_delay=0)
            real_sleep(0.5)
        except SystemExit:
            pass
check("a broken runner loop is reported", any(r["source"] == "routines" for r in alerts.read()))
alerts.clear()

# quick tasks
check("task by voice", "Task saved" in said("task: buy a cable") and "Task saved" in said("add task call the library"))
said("new task: email me@example.com the form")
check("tasks keep the date and are masked", date.today().isoformat() in (tmp / "tasks.md").read_text() and "me@example.com" not in (tmp / "tasks.md").read_text())
check("list tasks numbers them", "3 open tasks" in said("list tasks") and tasks.describe().startswith("1. buy a cable"))
check("done N marks the Nth open task", "call the library" in said("done 2") and [t["text"] for t in tasks.open_items()][1].startswith("email"))
check("done also takes number words", "buy a cable" in said("mark task one done"))
check("a hand edited line is read", (tmp / "tasks.md").write_text((tmp / "tasks.md").read_text() + "- [ ] 2026-11-01 water the plant\n") and any("plant" in t["text"] for t in tasks.open_items()))
check("clear done removes only finished tasks", "Cleared 2" in said("clear done") and len(tasks.rows()) == 2)
check("done with no such task", "open task" in said("done 9"))
check("an empty task asks what it is", "What is the task" in said("task: -"))

# open tasks reach the brief
with mock.patch.object(brain, "ask", lambda *a, **k: "Fine."):
    note = morning.build(datetime.now())
check("open tasks are in the brief", "water the plant" in note["text"] and "## Tasks" in note["text"])
alerts.add("x", "a failure")
with mock.patch.object(brain, "ask", lambda *a, **k: "Fine."):
    check("open alerts are in the brief", "## Alerts" in morning.build(datetime.now())["text"])

patch.stop()
print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}")
sys.exit(1 if bad else 0)
