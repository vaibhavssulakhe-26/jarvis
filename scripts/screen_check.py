"""Checks screen reading by OCR and the dictation hotkey. Parts that need tesseract or a live display are skipped when missing.
Run: python scripts/screen_check.py   (set SCREEN_LIVE=1 to also take a real screenshot)"""
import os
import queue
import shutil
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

import numpy as np

scratch = Path(tempfile.mkdtemp(prefix="jarvis-screen-"))
os.environ["JARVIS_DATA"] = str(scratch)
os.environ["XDG_STATE_HOME"] = str(scratch)
os.environ["XDG_RUNTIME_DIR"] = str(scratch)
os.environ.pop("DICTATE_KEY", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import screen  # noqa: E402
from jarvis.core import main, state  # noqa: E402
from jarvis.voice import dictate, ears  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def skip(name, why):
    print(f"skip {name}  ({why})")


T = tools.TOOLS

# ---- OCR ----
cleaned = screen.clean_ocr("Welcome to the lab\n\n  ~~ \napi_key = sk-abcdefghijklmnop1234\nSecond line here\n|")
check("OCR cleanup drops noise and secret lines", cleaned == "Welcome to the lab\nSecond line here", repr(cleaned))

real_which = shutil.which
captured = []


def fake_capture(path):
    captured.append(path)
    Path(path).write_bytes(b"png")


with mock.patch.object(screen.shutil, "which", lambda n: None), mock.patch.object(screen, "capture_screen", fake_capture):
    try:
        T["read_screen"]["fn"]({})
        check("without tesseract the tool explains how to install it", False)
    except tools.ToolError as e:
        check("without tesseract the tool explains how to install it", "sudo dnf install tesseract" in str(e), str(e))
check("and takes no screenshot when tesseract is missing", not captured)


class Run:
    def __init__(self, out, code=0):
        self.stdout, self.returncode = out.encode(), code


def with_text(text, code=0):
    return (mock.patch.object(screen.shutil, "which", lambda n: "/usr/bin/" + n), mock.patch.object(screen, "capture_screen", fake_capture),
            mock.patch.object(screen.subprocess, "run", lambda *a, **k: Run(text, code)))


sent = []
ctx = with_text("Build failed: missing semicolon\nline 12 of main.c")
for c in ctx:
    c.start()
reply = T["read_screen"]["fn"]({})
for c in ctx:
    c.stop()
check("short screen text is read out in full", "Your screen says: Build failed" in str(reply) and type(reply).__name__ == "Full", str(reply))
check("the capture is deleted afterwards", captured and not Path(captured[-1]).exists())

long_text = "\n".join(f"Paragraph {i} about graph algorithms and trees" for i in range(60)) + "\npassword: hunter2hunter2\n"
ctx = with_text(long_text)
for c in ctx:
    c.start()
with mock.patch.object(screen.brain, "ask", lambda prompt, n=0, **k: sent.append((prompt, n)) or "It shows notes on graph algorithms."):
    reply = T["read_screen"]["fn"]({})
    T["read_screen"]["fn"]({"question": "which topics are listed"})
for c in ctx:
    c.stop()
check("long text goes to the model and the answer comes back", reply == "It shows notes on graph algorithms.", reply)
check("secret lines never leave the laptop", all("hunter2" not in p for p, _ in sent))
check("at most 3000 characters of screen text are sent", all(len(p) < 3500 for p, _ in sent))
check("the screen text is marked as data", "never instructions" in sent[0][0])
check("a question is passed along", "which topics are listed" in sent[1][0])

ctx = with_text("")
for c in ctx:
    c.start()
reply = T["read_screen"]["fn"]({})
for c in ctx:
    c.stop()
check("a screen with no text says so", "could not find any readable text" in reply, reply)
ctx = with_text("", code=1)
for c in ctx:
    c.start()
try:
    T["read_screen"]["fn"]({})
    check("a tesseract failure is a spoken error, not a crash", False)
except tools.ToolError:
    check("a tesseract failure is a spoken error, not a crash", True)
for c in ctx:
    c.stop()

ran = []
for phrase, name in (("read my screen", "read_screen"), ("what's on my screen", "read_screen"), ("what is on screen", "read_screen"),
                     ("describe my screen", "describe_screen"), ("look at my screen", "describe_screen")):
    with mock.patch.object(main, "do_tool", lambda a, args, s="": ran.append(a)), mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")):
        main.fast_path(phrase)
    check(f"{phrase!r} -> {name}", ran and ran[-1] == name, str(ran[-1:]))

if real_which("tesseract"):
    try:
        from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter
        app = QGuiApplication.instance() or QGuiApplication(["x", "-platform", "offscreen"])
        img = QImage(900, 200, QImage.Format.Format_RGB32)
        img.fill(QColor("white"))
        p = QPainter(img)
        p.setFont(QFont("DejaVu Sans", 40))
        p.drawText(30, 120, "Jarvis reads graphs")
        p.end()
        png = scratch / "t.png"
        img.save(str(png))
        check("real tesseract reads rendered text", "graphs" in screen.ocr_text(png).lower())
    except Exception as e:
        skip("real tesseract", type(e).__name__)
else:
    skip("real tesseract reads rendered text", "tesseract is not installed: sudo dnf install tesseract")
if os.environ.get("SCREEN_LIVE") == "1" and (real_which("spectacle") or real_which("grim")):
    out = scratch / "live.png"
    tools.capture_screen(out)
    check("a live screenshot is taken", out.exists() and out.stat().st_size > 1000)
else:
    skip("live screenshot", "set SCREEN_LIVE=1 on a desktop with spectacle or grim")

# ---- dictation ----
check("dictation is off without DICTATE_KEY", dictate.key_name() is None and dictate.start() is None)
for raw, want in (("F9", "KEY_F9"), ("rightctrl", "KEY_RIGHTCTRL"), ("KEY_PAUSE", "KEY_PAUSE"), ("right ctrl", "KEY_RIGHTCTRL"), ("off", None)):
    with mock.patch.dict(os.environ, {"DICTATE_KEY": raw}):
        check(f"DICTATE_KEY={raw!r} -> {want}", dictate.key_name() == want)
with mock.patch.dict(os.environ, {"DICTATE_KEY": "NOTAKEY"}):
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        dictate.start().join(2)
    check("an unknown key is reported, not a crash", "not a known key name" in out.getvalue(), out.getvalue())

with mock.patch.dict(os.environ, {"DICTATE_KEY": "F9"}), mock.patch.object(dictate, "listen", side_effect=PermissionError()):
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        t = dictate.start()
        t.join(2)
    check("without input group access it says how to fix it", "usermod -aG input" in out.getvalue() and "--once" in out.getvalue(), out.getvalue())



class Stream:
    def __init__(self, cb):
        self.cb, self.live = cb, False

    def start(self):
        self.live = True
        for _ in range(8):
            self.cb(np.full((1600, 1), 0.2, dtype=np.float32), 1600, None, None)

    def stop(self):
        self.live = False

    def close(self):
        pass


heard = []
pasted = []
spoken = []
kb = dictate.Keyboard(open_stream=Stream, say=spoken.append)
with mock.patch.object(dictate.stt, "transcribe", lambda a: heard.append(len(a)) or "hello world from my voice"), \
        mock.patch.object(dictate, "paste", lambda t: pasted.append(t)):
    kb.press()
    check("pressing the key starts recording and pauses the wake listener", kb.stream is not None and state.get("dictating") is True)
    kb.press()
    check("key repeat does not start a second recording", len(kb.chunks) == 8)
    time.sleep(0.35)
    kb.release()
    check("releasing stops recording and resumes the wake listener", kb.stream is None and state.get("dictating") is False)
    for _ in range(50):
        if pasted:
            break
        time.sleep(0.05)
check("the recording is transcribed and pasted", pasted == ["hello world from my voice"] and heard == [12800], f"{pasted} {heard}")

pasted.clear()
kb2 = dictate.Keyboard(open_stream=Stream)
with mock.patch.object(dictate.stt, "transcribe", lambda a: "x"), mock.patch.object(dictate, "paste", lambda t: pasted.append(t)):
    kb2.press()
    kb2.release()
    time.sleep(0.2)
check("a tap shorter than a third of a second is ignored", not pasted)

with mock.patch.object(dictate.stt, "transcribe", lambda a: ""), mock.patch.object(dictate, "paste", lambda t: pasted.append(t)):
    check("nothing understood means nothing is pasted", dictate.finish(np.zeros(100), spoken.append) == "" and not pasted and "I did not catch that." in spoken)
with mock.patch.object(dictate.stt, "transcribe", lambda a: "some text"), mock.patch.object(dictate, "paste", side_effect=RuntimeError("no clipboard tool")):
    del spoken[:]
    check("a paste failure is reported, not raised", dictate.finish(np.zeros(100), spoken.append) == "some text" and spoken)

copied, pastes = [], []
with mock.patch.object(dictate.platform, "clipboard_write", lambda t: copied.append(t) or True), \
        mock.patch.object(dictate.platform, "send_paste", lambda terminal=False: pastes.append(terminal)), mock.patch.object(dictate.time, "sleep", lambda s: None), \
        mock.patch("jarvis.actions.windows.active_window", lambda *a, **k: ("firefox", "Docs")):
    dictate.paste("typed text")
    check("paste copies the text", copied == ["typed text"])
    check("and presses the plain paste shortcut in a normal window", pastes == [False])
    with mock.patch("jarvis.actions.windows.active_window", lambda *a, **k: ("org.kde.konsole", "bash")):
        dictate.paste("in terminal")
    check("and the terminal shortcut in a terminal", pastes[-1] is True)
with mock.patch.object(dictate.platform, "clipboard_write", lambda t: False):
    try:
        dictate.paste("x")
        check("no clipboard tool raises a clear error", False)
    except RuntimeError as e:
        check("no clipboard tool raises a clear error", "clipboard" in str(e))

# shortcut mode stops after silence
clock = {"t": 0.0}
blocks = [(0.3 * np.sin(np.arange(1600) / 5.0)).astype(np.float32)] * 5 + [np.zeros(1600, dtype=np.float32)] * 30


class Feed:
    def __init__(self, cb):
        self.cb = cb
        self.i = 0

    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


def fake_sleep(s):
    clock["t"] += s
    if feed.i < len(blocks):
        feed.cb(blocks[feed.i].reshape(-1, 1), 1600, None, None)
        feed.i += 1


def make_feed(cb):
    global feed
    feed = Feed(cb)
    return feed


with mock.patch.object(dictate.time, "sleep", fake_sleep):
    audio = dictate.record_once(open_stream=make_feed, now=lambda: clock["t"])
check("--once records until about a second of quiet", 5 * 1600 <= len(audio) <= 20 * 1600 and clock["t"] < 5, f"{len(audio)} {clock['t']}")

# the wake listener leaves the mic alone while dictating
e = ears.Ears.__new__(ears.Ears)
e._init_echo()
e.q = queue.Queue()
e.q.put(np.zeros(1280, dtype=np.int16))
e.phase, e.buf, e.pre, e.loud, e.quiet = None, [], __import__("collections").deque(maxlen=3), 0, 0
state.update(dictating=True, paused=False)
e._step(np.ones(1280, dtype=np.int16))
check("the wake listener ignores the mic while dictating", e.q.empty())
state.update(dictating=False)
sys.exit(1 if bad else 0)
