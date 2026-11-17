"""Smart quotes, an em dash, Hindi and Kannada through the router, chat, logs, files, API replies and the dashboard. Run: python scripts/encoding_check.py"""
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QT_LOGGING_RULES"] = "qt.text.font.db=false"
tmp = Path(tempfile.mkdtemp(prefix="jarvis-utf8-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
os.environ["JARVIS_DASH_TEST"] = "1"
os.environ.pop("GROQ_API_KEY", None)
os.environ.pop("OPENROUTER_API_KEY", None)
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

TEXT = "It’s a “quoted” line — नमस्ते ಕನ್ನಡ"
bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


import requests  # noqa: E402
from PyQt6.QtCore import QCoreApplication  # noqa: E402
from PyQt6.QtGui import QFontMetrics  # noqa: E402
from PyQt6.QtWidgets import QApplication, QLabel, QTextEdit  # noqa: E402

from jarvis import tasks, traces  # noqa: E402
from jarvis.actions import coder, procs, tools  # noqa: E402,F401
from jarvis.brain import brain  # noqa: E402
from jarvis.core import config, jsonfile, main as core  # noqa: E402
from jarvis.memory import threads  # noqa: E402
from jarvis.voice import voice  # noqa: E402


def pump(seconds):
    end = time.time() + seconds
    while time.time() < end:
        QCoreApplication.processEvents()
        time.sleep(0.01)


app = QApplication.instance() or QApplication(sys.argv)

# the router and a tool that writes a file
with voice.capture() as lines:
    core.handle("task: " + TEXT)
check("the router passes the text to a tool unchanged", any("Task saved" in x for x in lines), str(lines))
raw = (tmp / "data" / "tasks.md").read_bytes()
check("the task file is UTF-8 on disk", TEXT.encode("utf-8") in raw)
check("and reads back the same", tasks.open_items()[0]["text"] == TEXT, str(tasks.open_items()))

# chat: a reply with the same characters, saved to the shared thread and read back
threads.attach()
reply = "You said: " + TEXT


def fake_chat(text, on_delta=None):
    return {"action": "chat", "say": reply}


with mock.patch.object(brain, "chat", fake_chat), mock.patch.object(brain, "tool_turn", lambda *a, **k: {"text": reply, "calls": [], "provider": "groq"}):
    core.events.emit("you", "once upon a time " + TEXT)
    core.handle("once upon a time " + TEXT)
msgs = threads.current()["messages"]
check("the chat thread keeps both lines", any(TEXT in m["text"] for m in msgs if m["role"] == "assistant") and any(TEXT in m["text"] for m in msgs if m["role"] == "user"), str([m["text"][:30] for m in msgs]))
thread_file = next((tmp / "data" / "chats").glob("*.json"))
check("the chat file is valid UTF-8 JSON", TEXT in json.loads(thread_file.read_bytes().decode("utf-8"))["messages"][-1]["text"])

# logs
row = traces.load()[-1]
check("the trace line keeps the text", TEXT in row["heard"], row["heard"])
trace_text = traces.path().read_bytes().decode("utf-8")
check("and the trace file is readable UTF-8", "नमस्ते" in trace_text)

# the terminal: an ASCII locale must not break a print
code = "from jarvis.core import main\nmain.utf8_streams()\nprint(" + repr(TEXT) + ")\n"
out = subprocess.run([sys.executable, "-"], input=code.encode("utf-8"), cwd=root, env={**os.environ, "PYTHONIOENCODING": "ascii", "LC_ALL": "C", "PYTHONUTF8": "0"}, capture_output=True)
check("printing Hindi and Kannada survives an ASCII terminal", out.returncode == 0 and TEXT.encode("utf-8") in out.stdout, out.stderr.decode("utf-8", "replace")[-200:])

# files, JSON, .env and child process output
jsonfile.write(tmp / "x.json", {"t": TEXT})
check("small JSON files round trip", jsonfile.read(tmp / "x.json") == {"t": TEXT})
envfile = tmp / ".env.test"
envfile.write_bytes(("USER_NICKNAME=" + TEXT + "\n").encode("utf-8"))
os.environ.pop("USER_NICKNAME", None)
config._read_env(envfile)
check(".env values are read as UTF-8", os.environ.get("USER_NICKNAME") == TEXT, str(os.environ.get("USER_NICKNAME")))
folder = tmp / "work" / "demo"
folder.mkdir(parents=True)
coder.write_project_file(folder, "index.html", "<p>" + TEXT + "</p>")
check("project files are written as UTF-8", (folder / "index.html").read_bytes().decode("utf-8") == "<p>" + TEXT + "</p>")
log = tmp / "child.log"
proc = procs.spawn("printer", [sys.executable, "-c", "print('" + TEXT.replace("'", "\\'") + "')"], tmp, procs.clean_env(), log)
proc.wait(10)
check("a child process's output is read back intact", TEXT in procs.tail(log, 5), procs.tail(log, 5))

# API replies: a streamed answer with no charset header, and a JSON answer
sse = "".join("data: " + json.dumps({"choices": [{"delta": {"content": part}}]}, ensure_ascii=False) + "\n\n" for part in (TEXT[:12], TEXT[12:])) + "data: [DONE]\n\n"


def streamed(body_bytes):
    r = requests.Response()
    r.status_code = 200
    r.headers["content-type"] = "text/event-stream"
    r.raw = io.BytesIO(body_bytes)
    r.__enter__ = lambda self=r: r
    return r


class Ctx:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        return self.r

    def __exit__(self, *a):
        return False


got = []
with mock.patch.object(brain._http, "post", lambda *a, **k: Ctx(streamed(sse.encode("utf-8")))):
    text, code = brain._groq_stream([{"role": "user", "content": "x"}], "m", 50, got.append)
check("a streamed Groq answer keeps Hindi and Kannada intact", text == TEXT and "".join(got) == TEXT, str(text))
r = requests.Response()
r.status_code = 200
r._content = json.dumps({"choices": [{"message": {"content": TEXT, "tool_calls": []}}]}, ensure_ascii=False).encode("utf-8")
r.headers["content-type"] = "application/json"
with mock.patch.object(brain._http, "post", lambda *a, **k: r):
    msg, code = brain._groq_tools([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}], [], 50)
check("a function-calling reply keeps the text intact", msg and msg["content"] == TEXT, str(msg))

# the dashboard
from jarvis.ui.dashboard import window  # noqa: E402

win = window.Dashboard()
win.show()
pump(0.3)
threads.add("user", TEXT)
threads.add("assistant", "**" + TEXT + "**", tier="fast")
pump(0.3)
chat = win.pages["Home"].chat
check("chat cards show the text", any(TEXT in b.body.toPlainText() for b in chat.bubbles if b.role == "user") and any(TEXT in b.body.toPlainText() for b in chat.bubbles if b.role == "assistant"))
window.events.emit("sys", "log " + TEXT)
window.events.emit("build", "build " + TEXT)
pump(0.2)
win.go("Activity")
win.pages["Activity"].refresh()
win.go("Code")
win.pages["Code"].refresh()
check("the activity log shows the text", TEXT in win.pages["Activity"].log.toPlainText())
check("the build log shows the text", TEXT in win.pages["Code"].log.toPlainText())
seen = []
with mock.patch.object(core, "handle", lambda text, via_wake=True: seen.append(text)):
    chat.entry.setText(TEXT)
    chat.send()
    win.cmd.setText(TEXT)
    win.send()
    pump(0.3)
check("typing the text in the chat box and the command bar sends it unchanged", seen == [TEXT, TEXT], str(seen))
label = QLabel(TEXT)
edit = QTextEdit()
edit.setPlainText(TEXT)
check("Qt widgets hold the text unchanged", label.text() == TEXT and edit.toPlainText() == TEXT)
metrics = QFontMetrics(win.font())
missing = [c for c in "नಕ" if not metrics.inFontUcs4(ord(c))]
print("     (a font with Devanagari and Kannada is installed)" if not missing else "     (note: no installed font covers Devanagari or Kannada, so they would show as boxes)")

print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}")
sys.stdout.flush()
os._exit(1 if bad else 0)
