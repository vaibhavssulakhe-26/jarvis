"""Checks the yes/no confirmation: loose yes forms, the rest of the sentence is dropped, and the window title is named.
Run: python scripts/confirm_check.py"""
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

d = tempfile.mkdtemp(prefix="jarvis-confirm-")
os.environ.update(JARVIS_DATA=d, XDG_STATE_HOME=d, XDG_RUNTIME_DIR=d)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import apps, tools  # noqa: E402,F401
from jarvis.core import main  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


said, closed = [], []


def fresh():
    main.PENDING.clear()
    del said[:], closed[:]


patches = [mock.patch.object(main.voice, "say", lambda t: said.append(str(t))), mock.patch.object(apps.windows, "close_active", lambda: closed.append(1)),
           mock.patch.object(apps.windows, "active_window", lambda max_age=2.0: ("org.kde.dolphin", "Downloads - Dolphin")),
           mock.patch.object(main.voice.SPEAKING, "is_set", lambda: False),
           mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")), mock.patch.object(main.brain, "chat", side_effect=AssertionError("brain"))]
for p in patches:
    p.start()

fresh()
main._handle("close the current window")
check("the question names the window", said and said[-1] == "Close Downloads - Dolphin? Say yes or no.", str(said))
check("and waits", main.PENDING.get("action") == "close_app" and not closed)

for phrase in ("yes", "yes close it", "Yes, close it.", "confirm", "close it", "yeah sure", "go ahead", "yes please close this window", "ok close"):
    fresh()
    main._handle("close the current window")
    n = len(said)
    keep = main._handle(phrase)
    check(f"{phrase!r} closes the window once and asks nothing more", closed == [1] and not main.PENDING and sum("Say yes or no" in x for x in said) == 1, f"{closed} {said}")

for phrase in ("no", "no don't", "cancel", "never mind"):
    fresh()
    main._handle("close the current window")
    main._handle(phrase)
    check(f"{phrase!r} cancels", not closed and not main.PENDING and sum("Say yes or no" in x for x in said) == 1, str(said))

# the sentence from the log
fresh()
main._handle("close the current window")
routed = []
with mock.patch.object(main, "direct", lambda t: routed.append(("direct", t)) or True), mock.patch.object(main, "fast_path", lambda t: routed.append(("fast", t)) or True):
    main._handle("Yes, close it, confirm it, I confirm close it")
check("the log sentence closes the window once", closed == [1] and not main.PENDING, f"{closed} {said}")
check("and routes nothing else", routed == [] and sum("Say yes or no" in x for x in said) == 1, f"{routed} {said}")
check("and says only 'Closed it.' after the question", said[-1] == "Closed it." and len(said) == 2, str(said))

fresh()
main._handle("close the current window")
main._handle("yes close it and open spotify")
check("the rest of a yes sentence is dropped, not routed again", closed == [1] and not main.PENDING and not any("Spotify" in s for s in said), str(said))

fresh()
main._handle("close the current window")
routed = []
with mock.patch.object(main, "direct", lambda t: routed.append(t) or True):
    main._handle("yes close it")
check("nothing from a confirmed sentence reaches the router", routed == [] and closed == [1], str(routed))
fresh()
main.PENDING.update({"action": "close_app", "args": {}, "until": time.time() + 60})
main.check_pending("close firefox")
check("a loose 'close firefox' is not taken for a yes", not closed)

fresh()
main.PENDING.update({"action": "close_app", "args": {}, "until": time.time() + 60})
check("an unrelated sentence cancels the question", main.check_pending("what time is it") is False and not main.PENDING and not closed)

fresh()
main._handle("close the current window")
main._handle("yes")
n = len(said)
main._handle("yes")
check("a second stray yes does nothing", closed == [1] and len(said) == n)

with mock.patch.object(apps.windows, "active_window", lambda max_age=2.0: None):
    fresh()
    main._handle("close this")
    check("with no readable window it still asks", said[-1] == "Close the current window? Say yes or no.", str(said))
for p in patches:
    p.stop()
sys.exit(1 if bad else 0)
