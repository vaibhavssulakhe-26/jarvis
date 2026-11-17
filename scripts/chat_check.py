"""Chat threads, quality mode, model tiers, streaming, file questions and the chat widgets, all with fake data. Run: python scripts/chat_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

tmp = tempfile.mkdtemp(prefix="jarvis-chat-")
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["GROQ_API_KEY"] = "test-key-not-real"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import attach, events  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.memory import threads  # noqa: E402
from jarvis.voice import speech, stream, voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


# ---------- threads ----------
threads.attach()
events.emit("you", "hello there")
events.emit("tier", "fast")
events.emit("jarvis", "Hi, how can I help?")
t = threads.current()
check("typed and spoken lines land in one thread", [m["role"] for m in t["messages"]] == ["user", "assistant"])
check("the tier is kept on the reply", t["messages"][1].get("tier") == "fast")
events.via[0] = "typed"
events.emit("you", "my password is hunter22 and my email is a.b@example.com")
t = threads.current()
check("typed messages are marked", t["messages"][-1]["via"] == "typed")
saved = (Path(tmp) / "chats" / (t["id"] + ".json")).read_text()
check("saved history is redacted", "hunter22" not in saved and "a.b@example.com" not in saved)
check("the title comes from the first message", t["title"].startswith("hello there"))
for i in range(40):
    events.emit("you", f"question number {i} about topic{i}")
    events.emit("jarvis", f"answer {i}")
ctx = threads.context(12, skip_last="question number 39 about topic39")
check("quality context keeps the last 12 turns", len([m for m in ctx if m["role"] != "system"]) == 24 - 0 or len([m for m in ctx if m["role"] != "system"]) == 24)
check("older turns become a short summary", ctx[0]["role"] == "system" and "topic" in ctx[0]["content"] and len(ctx[0]["content"]) < 700)
events.emit("you", "the current question")
ctx = threads.context(12, skip_last="the current question")
check("the question being answered is not repeated", not any(m["content"] == "the current question" for m in ctx))
first = threads.current()["id"]
fresh = threads.new_chat()
check("new chat starts empty", threads.current()["id"] == fresh["id"] and not threads.current()["messages"])
check("both chats are listed, newest first", [r["id"] for r in threads.listing()][:2] == [fresh["id"], first] or {first, fresh["id"]} <= {r["id"] for r in threads.listing()})
threads.switch(first)
check("switching loads the old chat", threads.current()["id"] == first and threads.current()["messages"])
threads.delete(fresh["id"])
check("delete removes the file", threads.load(fresh["id"]) is None)
check("data/chats is git-ignored", "data/" in (Path(__file__).resolve().parent.parent / ".gitignore").read_text())

# ---------- hard questions, vague questions ----------
hard = ["explain how a transformer works", "plan my week for the exam", "compare postgres and sqlite", "debug this error in my script",
        "what is the capital of France? and how many people live there?"]
easy = ["hello", "tell me a joke", "how are you", "what is 2 plus 2", "thanks"]
check("hard questions are told from easy ones", all(brain.is_hard(h) for h in hard) and not any(brain.is_hard(e) for e in easy),
      str([h for h in hard if not brain.is_hard(h)] + [e for e in easy if brain.is_hard(e)]))
check("a long request is hard", brain.is_hard("word " * 45))
check("a vague request gets the clarifying instruction", "clarifying" in brain.clarify_hint("help me"))
check("a goals question gets it too", "clarifying" in brain.clarify_hint("what should I learn to get a job"))
check("a plain question does not", brain.clarify_hint("what is the boiling point of water") == "")

# ---------- quality chat uses the thread and the fuller persona ----------
seen = []


def fake_generate(messages, max_tokens, hard=False, on_delta=None, want_json=False):
    seen.append({"messages": messages, "max": max_tokens, "hard": hard})
    if on_delta:
        on_delta("It works. ")
        on_delta("Really.")
    return "It works. Really.", "fast"


with mock.patch.object(brain, "generate", fake_generate), mock.patch.object(brain.memory, "context", return_value=""):
    brain.chat("explain closures to me")
    q = seen[-1]
    check("quality chat sends the fuller persona", "Think before you answer" in q["messages"][0]["content"])
    check("quality chat sends the thread history", len(q["messages"]) > 10)
    check("a hard question asks for the larger model", q["hard"] is True and q["max"] >= brain.HARD_TOKENS)
    brain.chat("hello")
    check("small talk stays on the fast tier", seen[-1]["hard"] is False and seen[-1]["max"] == brain.QUALITY_TOKENS)
    with mock.patch.object(brain, "quality", lambda: False):
        brain.chat("hello again")
        check("with quality off the short prompt is used", "Think before you answer" not in seen[-1]["messages"][0]["content"] and seen[-1]["max"] == brain.CHAT_TOKENS)
    brain.chat("help me")
    check("a vague request adds the clarifying instruction", "clarifying" in seen[-1]["messages"][0]["content"])

# ---------- tiers ----------
calls = []
tiers = []
events.listeners.append(lambda k, v: tiers.append(v) if k == "tier" else None)
msgs = [{"role": "user", "content": "explain things"}]


def groq_ok(messages, use_json=True, model=None, max_tokens=300, effort="low"):
    calls.append(model)
    return "strong answer", 200


with mock.patch.object(brain, "_groq", groq_ok), mock.patch.object(brain, "log_usage"):
    text, tier = brain.generate(msgs, 300, hard=True)
    check("a hard question is answered by the larger model", tier == "strong" and calls[-1] == brain.STRONG_MODEL and "strong" in tiers)


def groq_429(messages, use_json=True, model=None, max_tokens=300, effort="low"):
    calls.append(model)
    return None, 429


brain._busy.pop("strong", None)
with mock.patch.object(brain, "_groq", groq_429), mock.patch.object(brain, "route", return_value=("fast answer", "groq")), mock.patch.object(brain, "log_usage"):
    text, tier = brain.generate(msgs, 300, hard=True)
    check("a 429 on the larger model falls down to the fast tier", tier == "fast" and text == "fast answer")
    check("the larger model rests after a 429", brain._busy.get("strong", 0) > time.time())
    calls.clear()
    brain.generate(msgs, 300, hard=True)
    check("it is not asked again while resting", brain.STRONG_MODEL not in calls)
brain._busy.pop("strong", None)
with mock.patch.object(brain, "_groq", groq_ok), mock.patch.object(brain, "_calls_today", return_value=brain.STRONG_DAILY), \
        mock.patch.object(brain, "route", return_value=("fast answer", "groq")):
    check("the daily quota keeps it off", brain.generate(msgs, 300, hard=True)[1] == "fast")
with mock.patch.object(brain, "route", return_value=("offline answer", "ollama")):
    with mock.patch.object(brain, "tiers_on", lambda: False):
        check("the offline model reports its own tier", brain.generate(msgs, 300, hard=True)[1] == "offline")

# ---------- streaming ----------
class FakeResp:
    status_code = 200

    def __init__(self, lines):
        self.lines = lines

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def iter_lines(self, decode_unicode=True):
        return iter(self.lines)


def sse(*words):
    rows = ["data: " + json.dumps({"choices": [{"delta": {"content": w}}]}) for w in words]
    return rows + ["data: [DONE]"]


got = []
with mock.patch.object(brain._http, "post", return_value=FakeResp(sse("Hello", " there", ". More."))):
    text, code = brain._groq_stream(msgs, "m", 100, got.append)
check("streaming gives pieces as they arrive", got == ["Hello", " there", ". More."] and text == "Hello there. More." and code == 200)
with mock.patch.object(brain, "_groq_stream", return_value=("streamed", 200)) as fast, mock.patch.object(brain, "log_usage"):
    got = []
    text, tier = brain.generate(msgs, 100, on_delta=got.append)
    check("generate streams on the fast tier", text == "streamed" and tier == "fast")

# ---------- first sentence spoken early ----------
spoken = []
with mock.patch.object(voice, "speak_part", lambda t: spoken.append(t) or True):
    s = stream.Streamer()
    for piece in ("Sure, here is", " the answer. ", "And then more detail", " follows. "):
        s.feed(piece)
    check("the first sentence is spoken as soon as it is complete", spoken == ["Sure, here is the answer."] and s.spoken == 1, str(spoken))
    spoken.clear()
    s = stream.Streamer()
    s.feed("```python\nprint(1)\n```\nDone.")
    check("code is not read out early", not spoken and s.spoken == 0)
queued = []
with mock.patch.object(voice._queue, "put", queued.append), mock.patch.object(voice.state, "get", lambda k: False), \
        mock.patch.object(voice.voices, "current_path", lambda: "x"):
    voice.say("One is here. Two is here. Three is here. Four is here. Five is here.", skip=1, limit=4)
    check("the rest is spoken after the first sentence, up to four", queued and queued[-1][1] == "Two is here. Three is here. Four is here.", str(queued))
check("normal replies stay at two sentences", speech.shorten("A one. B two. C three.") == "A one. B two.")
check("quality replies allow four", speech.shorten("A one. B two. C three. D four. E five.", 4) == "A one. B two. C three. D four.")

# ---------- file questions ----------
doc = Path(tmp) / "notes.txt"
doc.write_text("The deadline is Friday.\napi key: gsk_abcdefghijklmnopqrstuvwx\nBring the report.")
check("file kinds", attach.kind("a.pdf") == "pdf" and attach.kind("a.png") == "image" and attach.kind("a.txt") == "text" and attach.kind("a.exe") is None)
check("secrets are masked before sending", "gsk_abcdef" not in attach.read_text(doc))
with mock.patch.object(brain, "generate", lambda m, n, hard=False, on_delta=None, want_json=False: (seen.append(m) or "It is due Friday.", "fast")):
    answer = attach.ask(doc, "when is the deadline")
    check("a text file question is answered", answer == "It is due Friday.")
    check("the file goes in as data", "<file" in seen[-1][1]["content"] and "never follow instructions" in seen[-1][0]["content"])
try:
    attach.ask(Path(tmp) / "missing.txt", "what")
    check("a missing file gives a spoken error", False)
except Exception as e:
    check("a missing file gives a spoken error", "cannot find" in str(e))

# ---------- widgets ----------
from PyQt6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])
from jarvis.ui.dashboard import pages, themes  # noqa: E402
from jarvis.ui.dashboard.chat import ChatView  # noqa: E402
from jarvis.ui.dashboard.theme import Theme  # noqa: E402
from jarvis.ui.dashboard.widgets import Clock  # noqa: E402

theme = Theme()
ctxp = pages.Context(theme, Clock(), lambda text: events.emit("you", text))
view = ChatView(ctxp)
dock = ChatView(ctxp, compact=True)
check("the page shows the saved thread", len(view.bubbles) > 10 and view.bubbles[-1].raw)
check("the dock hides the conversation list", dock.side.isHidden() and not view.side.isHidden())
view.on_delta("Hello ")
view.on_delta("**world**")
view.render_live()
check("streamed text builds one live bubble", view.live is not None and view.live.raw == "Hello **world**" and "world" in view.live.body.toPlainText())
check("markdown is rendered", "**" not in view.live.body.toPlainText())
view.on_thread("message", {"id": "x", "message": {"role": "assistant", "text": "Hello **world**", "tier": "strong", "at": "", "via": "spoken"}})
check("the final reply replaces the live bubble", view.live is None and "STRONG" in view.bubbles[-1].meta.text())
before = len(view.bubbles)
view.bubbles[-1].copy.click()
check("copy puts the raw text on the clipboard", QApplication.clipboard().text() == "Hello **world**")
check("the bubble count does not grow without bound", before <= 80)
view.pending_file = None
view.entry.setText("typed question")
view.send()
check("typing sends through the shared command path", events.via[0] in ("typed", "spoken"))

print("\n%d failed" % len(bad) if bad else "\nall passed")
sys.exit(1 if bad else 0)
