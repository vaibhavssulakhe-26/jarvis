"""While the local model generates, the window gives it the CPU (15 fps, no particles, cursor effects paused) and takes it back afterwards; one Activity line per
local turn says the prompt tokens, time to the first word and whether the UI was throttled; identical error replies in a chat collapse into one message with a count.
Run: QT_QPA_PLATFORM=offscreen python scripts/throttle_check.py"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
tmp = Path(tempfile.mkdtemp(prefix="jarvis-throttle-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["JARVIS_DASH_TEST"] = "1"
for name in ("OLLAMA_URL", "OLLAMA_HOST", "OLLAMA_MODEL", "BRAIN", "BRAIN_MODE", "HTTP_PROXY", "HTTPS_PROXY"):
    os.environ.pop(name, None)
(tmp / "data").mkdir()
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "scripts" / "fakes"))

problems = []


def _hook(t, v, tb):
    import traceback
    problems.append("".join(traceback.format_exception(t, v, tb)))
    traceback.print_exception(t, v, tb)


sys.excepthook = _hook

import fake_ollama  # noqa: E402
import psutil  # noqa: E402
from PyQt6.QtCore import QCoreApplication, QPoint, Qt  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

from jarvis import traces  # noqa: E402
from jarvis.actions import events, tools  # noqa: E402,F401
from jarvis.brain import brain, local  # noqa: E402
from jarvis.memory import threads  # noqa: E402
from jarvis.ui import design  # noqa: E402

bad = []
log = []
events.listeners.append(lambda k, v: log.append((k, v)))


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


def until(cond, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        if cond():
            return True
        time.sleep(0.01)
    return False


app = QApplication.instance() or QApplication(sys.argv)
mock.patch.object(psutil, "virtual_memory", lambda: mock.Mock(available=3 * 2 ** 30, percent=50)).start()
mock.patch.object(brain, "_ensure_ollama", lambda: True).start()
mock.patch.object(brain, "_free_gb", lambda: 3.0).start()
mock.patch.object(brain, "_ollama_model", lambda: "llama3.2:1b").start()

# ---- the budget itself ----
b = design.budget(busy=True)
check("the busy budget is 15 fps with no particles and no cursor effects", b.fps == 15 and b.particles == 0 and not b.cursor and not b.tilt and b.trail == 0 and not b.ripples and not b.parallax and not b.drift)
check("a normal budget keeps them", design.budget().cursor and design.budget().particles == 300)
check("reduced motion is not busy", design.budget(reduced=True).cursor)

# ---- the window ----
from jarvis.ui import shell  # noqa: E402
sh = shell.Shell()
sh.resize(1280, 800)
sh.show()
pump(0.4)
stage, clock = sh.stage, sh.dash.clock
check("before a turn: 30 fps, particles, cursor effects", clock.interval == 33 and stage.budget.particles == 300 and stage.budget.cursor and not local.generating())
stage.cursor_override = (1000, 150)
for _ in range(30):
    stage.tick(1 / 30)
check("the cursor effects work before the turn", stage.globe.tilt[0] > 0.1 and stage.engaged > 0.9)

seen = {}
srv = fake_ollama.start(first_delay=0.8, reply=[f"w{i} " for i in range(6)], gap=0.25, loaded=["llama3.2:1b"])
local._use["url"] = srv.url
local.FIRST_COLD, local.FIRST_WARM, local.GAP_SECONDS = 5, 5, 3
log.clear()
brain.HEALTH.clear()


def run():
    seen["result"] = brain._try_ollama([{"role": "user", "content": "can you hear me?"}], 100, False)


t = threading.Thread(target=run, daemon=True)
t.start()
check("generation starts and the window drops to low power", until(lambda: local.generating() and clock.interval == 66 and stage.budget.particles == 0, 2),
      f"{local.generating()} {clock.interval} {stage.budget.particles}")
check("the particles are gone and the cursor effects paused", stage.stars.count == 0 and not stage.budget.cursor and not stage.budget.tilt)
stage.cursor_override = (150, 700)
tilt0 = list(stage.globe.tilt)
for _ in range(40):
    stage.tick(1 / 30)
check("while busy the globe no longer follows the cursor", stage.engaged < 0.2 and abs(stage.globe.tilt[0]) < abs(tilt0[0]) + 0.01 and stage.globe.spot_level < 0.2, f"{stage.engaged} {stage.globe.tilt}")
stage.ripples.clear()
QTest.mouseClick(stage, Qt.MouseButton.LeftButton, pos=QPoint(60, 60))
check("and a click makes no ripple", not stage.ripples)
check("the classic window pill would show the throttle too", sh.dash.throttled)
t.join(10)
check("the call finished with the answer", seen.get("result") and seen["result"][0].count("w") == 6, str(seen))
check("afterwards the window is back to 30 fps with particles and cursor effects", until(lambda: not local.generating() and clock.interval == 33 and stage.budget.particles == 300
      and stage.budget.cursor, 2), f"{clock.interval} {stage.budget.particles}")
check("the particles are restored", stage.stars.count == 300)
stage.cursor_override = (1000, 150)
for _ in range(40):
    stage.tick(1 / 30)
check("and the cursor effects work again", stage.globe.tilt[0] > 0.1 and stage.engaged > 0.9)

# ---- the Activity line ----
lines = [v for k, v in log if k == "sys" and v.startswith("local model turn")]
check("exactly one Activity line for the turn", len(lines) == 1, str(lines))
line = lines[0] if lines else ""
check("it has the prompt tokens", "prompt 42 tokens" in line, line)
check("it has the time to the first word", "first word 0." in line or "first word 1." in line, line)
check("and warm or cold", "(warm)" in line, line)
check("it says the UI was throttled", "UI throttled yes" in line, line)
check("it is a plain line the window does not take for a fault", not any(w in line.lower() for w in ("error", "failed", "stopped")))
check("the same facts are kept for the doctor", local.LAST.get("turn", {}).get("throttled") is True and local.LAST["turn"]["total"] > 1)

# a turn with no window to throttle
sh2_listeners = list(local.listeners)
local.listeners.clear()
log.clear()
brain._try_ollama([{"role": "user", "content": "hello"}], 100, False)
line2 = next((v for k, v in log if k == "sys" and v.startswith("local model turn")), "")
check("with no window listening the line says not throttled", "UI throttled no" in line2, line2)
local.listeners.extend(sh2_listeners)

# a failed turn also gets its line, and the throttle is lifted afterwards
srv.stop()
srv = fake_ollama.start(chat_status=404, chat_body="model not found")
local._use["url"] = srv.url
log.clear()
res = brain._try_ollama([{"role": "user", "content": "hi"}], 100, False)
fail_line = next((v for k, v in log if k == "sys" and v.startswith("local model turn")), "")
check("a failed turn is logged with its kind", res[0] is None and "no answer after" in fail_line and "(missing)" in fail_line and "UI throttled" in fail_line, fail_line)
check("and the window is restored after a failure", until(lambda: clock.interval == 33 and not local.generating(), 2))
srv.stop()
srv = fake_ollama.start(first_delay=3.0)
local._use["url"] = srv.url
local.FIRST_COLD = 1
res = brain._try_ollama([{"role": "user", "content": "hi"}], 100, False)
check("and after a timeout", res[0] is None and until(lambda: clock.interval == 33 and not local.generating() and stage.budget.cursor, 2))
srv.stop()

# two turns overlapping count as one busy period
with local.Generation():
    with local.Generation():
        check("nested calls keep it busy", local.generating())
    check("until the last one ends", local.generating())
check("then it is free", not local.generating())
pump(0.2)
check("the window follows", clock.interval == 33)
with mock.patch.object(local.Generation, "__exit__", lambda self, *a: (_ for _ in ()).throw(RuntimeError("x"))):
    pass

# a manual low power setting is not undone by a turn
sh.dash.set_low_power(True)
with local.Generation():
    pump(0.1)
pump(0.1)
check("a turn does not undo the user's own low power setting", clock.interval == 66 and sh.dash.low_manual)
sh.dash.set_low_power(False)
pump(0.1)

# ---- repeated error replies collapse ----
threads.new() if hasattr(threads, "new") else None
t0 = len(threads.current()["messages"])
threads.add("user", "play something")
first = threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
threads.add("user", "play something")
second = threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
threads.add("user", "play something")
third = threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
msgs = threads.current()["messages"][t0:]
assistant = [m for m in msgs if m["role"] == "assistant"]
check("three identical error replies are one message", len(assistant) == 1 and assistant[0]["count"] == 3 and second["count"] == 2 and third["count"] == 3, str(len(assistant)))
check("the user's own messages are all kept", sum(1 for m in msgs if m["role"] == "user") == 3)
threads.add("user", "what time is it")
threads.add("assistant", "It is ten past four.")
threads.add("user", "play something")
fourth = threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
check("after a good answer the same error starts a new message", "count" not in fourth and fourth["text"] == first["text"] and fourth.get("error"))
threads.add("user", "again")
other = threads.add("assistant", "The local model ran out of memory loading llama3.2:1b.", error=True)
check("a different error is a new message", other["text"] != fourth["text"] and "count" not in other)
threads.add("user", "ok")
a = threads.add("assistant", "Sure thing.")
threads.add("user", "ok")
b2 = threads.add("assistant", "Sure thing.")
check("identical ordinary replies are never collapsed", sum(1 for m in threads.current()["messages"] if m["text"] == "Sure thing.") == 2 and "count" not in b2)
check("the count is saved with the thread", threads.load(threads.current()["id"])["messages"][t0 + 1].get("count") == 3)
check("the error is classified from the failed trace", (traces.begin("x"), traces.fail("no brain"), threads.is_error_reply("Nothing today"), traces.end())[2])
check("and from the words", threads.is_error_reply("I could not reach the brain") and not threads.is_error_reply("Here is your answer"))
heard = []
threads.changed.append(lambda kind, info: heard.append(kind))
threads.add("user", "x")
threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
threads.add("user", "x")
threads.add("assistant", "The local model is still warming up, so I could not answer yet.", error=True)
check("listeners hear an update for a collapsed reply", "update" in heard)
check("the thread records an error reply through the event bus", (threads.attach(), events.emit("you", "q"), events.emit("jarvis", "I could not reach the model"), events.emit("you", "q"),
      events.emit("jarvis", "I could not reach the model"))[0] is None and [m for m in threads.current()["messages"] if m["role"] == "assistant"][-1].get("count") == 2, str(threads.current()["messages"][-2:]))

# ---- the chat window shows the count ----
hub = sh.dash.pages["Chat"].view
hub.load()
shown = [b.raw for b in hub.bubbles]
check("the chat shows the count on the collapsed message", any("(×2)" in t and "could not reach the model" in t for t in shown), str(shown[-3:]))
check("and one bubble for it", sum(1 for t in shown if "could not reach the model" in t) == 1)
threads.add("user", "x")
threads.add("assistant", "I could not reach the model", error=True)
pump(0.3)
check("a further repeat updates the visible bubble", any("(×3)" in b.raw for b in hub.bubbles), str([b.raw for b in hub.bubbles][-3:]))
check("no exception reached the Qt event loop", not problems, "".join(problems)[-500:])

sh.tray = None
with mock.patch("jarvis.ui.ui.mpvctl.stop", lambda: None), mock.patch("jarvis.ui.ui.browser.shutdown", lambda: None), mock.patch("jarvis.ui.ui.brain.finish", lambda: None):
    sh.quit_all(exit_process=False)
check("quitting removes the window's listener", not local.listeners or all(fn.__self__ is not sh.dash.bus for fn in local.listeners if hasattr(fn, "__self__")))
sys.exit(1 if bad else 0)
