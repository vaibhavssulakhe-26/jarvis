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
e.barge_thr = ears.barge_threshold(0.4)
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
    check("the raised threshold is above the normal one", e.barge_thr > e.wake_thr)
    with mock.patch.dict(os.environ, {"BARGE_THRESHOLD": "0.8"}):
        check("BARGE_THRESHOLD is separate from WAKE_THRESHOLD", ears.barge_threshold(0.2) == 0.8)
    check("without BARGE_THRESHOLD it follows the wake threshold", abs(ears.barge_threshold(0.2) - 0.5) < 1e-9)
    e._step(blocks(0.9)[0])
    check("the wake word while speaking cuts the audio", len(cuts) == 1)
    check("and Jarvis starts listening for the command", e.phase == "wait" and e.via_wake)

# follow-up window: no wake word needed for a while after a reply, closed by thanks / bye / silence, shut while media plays
said_f, asked_f = [], []
f = ears.Ears.__new__(ears.Ears)
f.followup, f.expect, f.awake_until, f.via_wake = 10.0, False, 0.0, False
f.q, f.oww = queue.Queue(), FakeOww()
f.noise, f.pre = [], __import__("collections").deque(maxlen=3)
f.buf, f.loud, f.quiet, f.n, f.thr, f.t0 = [], 0, 0, 0, 0.02, 0.0
f.phase, f.cool_until, f.deaf_until, f.chimed, f.reported = None, 0.0, 0.0, False, True
f.debug, f.debug_at, f.barge_thr, f.wake_thr = False, 0.0, 0.7, 0.4
heard = {"text": "open youtube"}
asked_f = []
playing = {"on": False}
real_after = ears.Ears._after
f._reset_wake = lambda: None


def run_hear(text, via=False):
    heard["text"] = text
    del said_f[:]
    del asked_f[:]
    f.awake_until = 0.0
    with mock.patch.object(ears.stt, "transcribe", lambda a: heard["text"]), mock.patch.object(ears.time, "sleep", lambda s: None), \
            mock.patch.object(ears.voice, "say", lambda t: said_f.append(str(t))), mock.patch.object(ears.voice, "wait", lambda: None), \
            mock.patch.object(ears.voice, "LAST", ["Done."]), mock.patch.object(ears.mpvctl, "playing", lambda: playing["on"]), \
            mock.patch.object(ears, "media_playing", lambda: playing["on"] or playing.get("other", False)), mock.patch.object(ears.events, "emit"), \
            mock.patch.object(ears.reminders, "active", lambda: None):
        f._handle(np.zeros(16000, dtype=np.float32), via)


f.on_command = lambda text, via: asked_f.append(text) or False
playing["on"] = False
before = time.time()
run_hear("open youtube", via=True)
check("a reply opens a ten second follow-up window", 9 < f.awake_until - before < 11, str(f.awake_until - before))
f.followup = 4.0
run_hear("open youtube", via=True)
check("the window length follows FOLLOWUP_SECONDS", 3 < f.awake_until - time.time() < 5)
f.followup = 10.0
with mock.patch.dict(os.environ, {"FOLLOWUP_SECONDS": "7"}):
    check("FOLLOWUP_SECONDS is read from the environment", ears.followup_seconds() == 7.0)
with mock.patch.dict(os.environ, {"FOLLOWUP_SECONDS": "x"}):
    check("a bad FOLLOWUP_SECONDS falls back to ten", ears.followup_seconds() == 10.0)
os.environ.pop("FOLLOWUP_SECONDS", None)
check("the default is ten seconds", ears.followup_seconds() == 10.0)
run_hear("what is the weather like today")
check("a follow-up without the wake word is handled", asked_f == ["what is the weather like today"], str(asked_f))
check("and it opens a fresh window", f.awake_until - time.time() > 9)
for phrase in ("thanks", "That's all", "bye", "stop listening", "thank you jarvis", "okay thanks"):
    run_hear(phrase)
    check(f"{phrase!r} closes the window without a model call", f.awake_until == 0.0 and not asked_f and len(said_f) == 1, f"{f.awake_until} {asked_f} {said_f}")
duck_state = {"on": False, "calls": 0}


def fake_duck():
    duck_state["calls"] += 1
    was = duck_state["on"]
    duck_state["on"] = True
    return not was


def fake_unduck():
    duck_state["on"] = False


duck_patches = [mock.patch.object(ears.mpvctl, "duck", fake_duck), mock.patch.object(ears.mpvctl, "unduck", fake_unduck),
                mock.patch.object(ears.mpvctl, "ducked", lambda: duck_state["on"])]
for dp in duck_patches:
    dp.start()
playing["on"] = True
run_hear("play some lofi", via=True)
check("the window stays open while mpv plays, with mpv turned down", f.awake_until - time.time() > 9 and duck_state["on"], str(f.awake_until))
duck_state["on"] = False
playing["on"], playing["other"] = False, True
run_hear("play some lofi", via=True)
playing["other"] = False
check("other players still close the window", f.awake_until == 0.0)
playing["on"] = True
duck_state["on"] = False
for phrase in ("stop playing", "pause", "resume", "next", "louder", "quieter"):
    run_hear(phrase)
    check(f"{phrase!r} works inside the window without the wake word", asked_f == [phrase], str(asked_f))
duck_state["on"] = False
playing["on"] = False
g = ears.Ears.__new__(ears.Ears)
g.__dict__.update({k: v for k, v in f.__dict__.items()})
g.thr, g.phase, g.loud, g.wake_thr = 0.02, None, 0, 0.4
loud_block = np.full(1280, 3000, dtype=np.int16)
silent_block = np.zeros(1280, dtype=np.int16)
quiet_oww = FakeOww()
g.oww = quiet_oww
for kind, on, window, want in (("window open, nothing playing", False, 5.0, "record"),
                               ("window open, media playing", True, 5.0, None),
                               ("window closed", False, -1.0, None)):
    g.phase, g.loud, g.awake_until = None, 0, time.time() + window
    duck_state["on"] = False
    playing["on"] = on
    with mock.patch.object(ears, "media_playing", lambda: playing["on"]), mock.patch.object(ears.events, "set_level"):
        for _ in range(3):
            g._idle(loud_block, 0.1, time.time())
    check(f"speech without the wake word: {kind}", g.phase == want, str(g.phase))
playing["on"] = False
g.phase, g.loud, g.awake_until = None, 0, time.time() + 5
with mock.patch.object(ears, "media_playing", lambda: False):
    for _ in range(5):
        g._idle(silent_block, 0.0, time.time())
check("silence does not start a recording", g.phase is None)
check("mpvctl.playing is false when mpv is not running", not ears.mpvctl.playing())

duck_state["on"] = True
g.phase, g.loud, g.awake_until = None, 0, time.time() + 5
playing["on"] = True
with mock.patch.object(ears, "media_playing", lambda: True), mock.patch.object(ears.events, "set_level"):
    for _ in range(3):
        g._idle(loud_block, 0.1, time.time())
check("speech in the window while mpv is turned down is recorded", g.phase == "record" and duck_state["on"], str(g.phase))
g.phase, g.loud, g.awake_until = None, 0, time.time() - 1
with mock.patch.object(ears.events, "set_level"):
    g._idle(silent_block, 0.0, time.time())
check("mpv is turned back up when the window ends", not duck_state["on"])
g._begin(time.time(), "wait")
check("listening turns mpv down", duck_state["on"])
g._reset()
duck_state["on"] = False
for dp in duck_patches:
    dp.stop()

import contextlib
import io
g.phase, g.awake_until, g.debug_at = None, 0.0, 0.0
for flag, score, want in ((True, 0.2, True), (True, 0.1, False), (False, 0.3, False)):
    g.debug, g.debug_at = flag, 0.0
    out = io.StringIO()
    with contextlib.redirect_stdout(out), mock.patch.object(ears.events, "set_level"):
        g._idle(np.full(1280, int(score * 100), dtype=np.int16), 0.0, time.time())
    check(f"WAKE_DEBUG={flag} score {score}: " + ("printed" if want else "silent"), ("wake score" in out.getvalue()) == want, out.getvalue())
g.debug = False
voice.SPEAKING.clear()
for p in patches:
    p.stop()
sys.exit(1 if bad else 0)
