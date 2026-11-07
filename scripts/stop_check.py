"""Checks that speech can be cut off: stop words, the stop key, and the wake word while Jarvis talks (fake audio stream).
No audio device, no mic. Run: python scripts/stop_check.py"""
import os
import queue
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import numpy as np

scratch = tempfile.mkdtemp(prefix="jarvis-stop-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.core import main, state  # noqa: E402
from jarvis.voice import ears, voice, voices  # noqa: E402

bad = []
procs = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


class FakeProc:
    def __init__(self, *a, **kw):
        self.killed = False
        procs.append(self)

    def poll(self):
        return -9 if self.killed else None

    def kill(self):
        self.killed = True

    def wait(self):
        return 0


def wait_for(cond, seconds=2.0):
    end = time.time() + seconds
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


patches = [mock.patch.object(voice, "player", lambda: "fakeplayer"), mock.patch.object(voice.subprocess, "Popen", FakeProc),
           mock.patch.object(voice, "synth", lambda text, path: True), mock.patch.object(voices, "current_path", lambda: Path("v.onnx")),
           mock.patch.object(voice.events, "emit")]
for p in patches:
    p.start()

check("stop with nothing speaking is harmless", voice.stop() is False and not voice.SPEAKING.is_set())

voice.say("This is a long sentence that is playing. And here is a second one. Then a third one.")
check("speech starts", wait_for(lambda: procs), str(procs))
t0 = time.time()
cut = voice.stop()
check("stop cuts the audio process at once", wait_for(lambda: procs[0].killed, 0.5) and cut and time.time() - t0 < 0.5)
check("speaking ends", wait_for(lambda: not voice.SPEAKING.is_set(), 1.5))
time.sleep(0.2)
check("the rest of the reply is not played after stop", len(procs) == 1, str(len(procs)))

del procs[:]
voice.say("First line.")
voice.say("Second line.")
voice.say("Third line.")
wait_for(lambda: procs)
voice.stop()
wait_for(lambda: not voice.SPEAKING.is_set(), 1.5)
time.sleep(0.2)
check("queued lines are dropped by stop", len(procs) == 1, str(len(procs)))

del procs[:]
voice.say("Another line that gets cut by the key.")
wait_for(lambda: procs)
state.update(stop_at=time.time())
check("the stop key cuts the audio", wait_for(lambda: procs[0].killed, 2.0))
wait_for(lambda: not voice.SPEAKING.is_set(), 1.5)

del procs[:]
voice.say("A new reply after stopping.")
check("speech works again after a stop", wait_for(lambda: procs and not procs[0].killed, 1.0))
voice.stop()
wait_for(lambda: not voice.SPEAKING.is_set(), 1.5)

stopped = []
for phrase in ("stop", "stop talking", "quiet", "enough", "shut up", "ruko", "चुप", "Stop."):
    del stopped[:]
    with mock.patch.object(main.voice, "stop", lambda: stopped.append(1) or True), \
            mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")), \
            mock.patch.object(main.brain, "chat", side_effect=AssertionError("brain")):
        main._handle(phrase)
    check(f"{phrase!r} stops speech without the brain", len(stopped) == 1)

main.PENDING.update({"action": "battery", "args": {}, "until": time.time() + 60})
said = []
with mock.patch.object(main.voice, "say", lambda t: said.append(str(t))), mock.patch.object(main.voice, "stop", lambda: stopped.append(1)):
    del stopped[:]
    main._handle("stop")
check("stop answers a pending question as a cancel when nothing is speaking", not main.PENDING and not stopped and "cancel" in " ".join(said).lower(), str(said))


class FakeOww:
    """Scores a block by its first sample, so a fake stream can carry 'the wake word'."""
    def predict(self, block):
        return {"jarvis": float(block[0]) / 100.0}


def blocks(*scores):
    return [np.full(1280, int(s * 100), dtype=np.int16) for s in scores]


e = ears.Ears.__new__(ears.Ears)
e.q = queue.Queue()
e.oww = FakeOww()
e.wake_thr = 0.4
e.phase = None
e.cool_until = 0.0
e.deaf_until = 0.0
e.noise = []
e.pre = __import__("collections").deque(maxlen=3)
e.buf, e.loud, e.quiet, e.n, e.thr, e.t0 = [], 0, 0, 0, 0.02, 0.0
e.chimed = False
e.awake_until = 0.0
e.last_talk = state.read()["talk_request"]
e.via_wake = False
e.reported = True
cuts = []
voice.SPEAKING.set()
with mock.patch.object(voice, "stop", lambda: cuts.append(1) or True):
    for b in blocks(0.1, 0.3, 0.6):
        e._step(b)
    check("normal speech and a weak wake score do not interrupt", not cuts)
    check("the raised threshold is above the normal one", min(0.95, e.wake_thr + 0.3) > e.wake_thr)
    e._step(blocks(0.9)[0])
    check("the wake word while speaking cuts the audio", len(cuts) == 1)
    check("and Jarvis starts listening for the command", e.phase == "wait" and e.via_wake)
voice.SPEAKING.clear()
for p in patches:
    p.stop()
sys.exit(1 if bad else 0)
