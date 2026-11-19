"""25 phrases that must always work, run end to end through the real router and tools with a scripted fake model, no network and no mic.
Writes data/core-check.json (shown on the Stats page); --scratch keeps the result out of data/. Run: python scripts/core_check.py"""
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="jarvis-core-"))
fake_home = tmp / "home"
for d in ("Pictures", "Documents", "Downloads"):
    (fake_home / d).mkdir(parents=True)
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
os.environ["HANDOFF_DIR"] = str(tmp / "outbox")
os.environ["HANDCTL_DIR"] = str(tmp / "handctl")
os.environ["FAKE_LOG"] = str(tmp / "bridge.log")
os.environ["NOTES_DIR"] = str(fake_home / "Documents" / "notes")
os.environ["GROQ_API_KEY"] = "gsk-fake-key-for-the-check-only"
os.environ["GROQ_VISION_MODEL"] = "fake-vision"
for k in ("BRAIN", "GMAIL_ADDRESS", "RAG_FOLDERS", "FILE_DENY"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))
os.environ["BRAIN_MODE"] = "hybrid"

for name in ("IMG_0001.jpg", "IMG_0002.jpg", "IMG_0003.jpg", "IMG_0004.jpg", "IMG_0005.jpg", "holiday.png"):
    (fake_home / "Pictures" / name).write_bytes(b"\x89fake")
(fake_home / "Documents" / "notes").mkdir()
(fake_home / "Documents" / "notes" / "graphs.md").write_text("# Graphs\nBreadth first search uses a queue and depth first search uses a stack.\n", encoding="utf-8")
(fake_home / "Documents" / "notes.txt").write_text("Meeting at five. Bring the report and the laptop charger.\n", encoding="utf-8")
(fake_home / "Documents" / "personal-diary.txt").write_text("secret", encoding="utf-8")

from scripts.fakes import fake_handctl  # noqa: E402

fake_handctl.make(tmp / "handctl")
from jarvis import platform  # noqa: E402
from jarvis.actions import apps, file_tools, files, handoff, play, screen, tools  # noqa: E402
from jarvis.brain import agent, brain  # noqa: E402
from jarvis.core import access, main as core  # noqa: E402
from jarvis.memory import rag  # noqa: E402
from jarvis.voice import voice  # noqa: E402

patches = [mock.patch("pathlib.Path.home", return_value=fake_home), mock.patch.object(file_tools, "HOME", fake_home), mock.patch.object(files, "HOME", fake_home)]
for p in patches:
    p.start()
rag.reindex(force=True)

MODEL_CALLS = []
SEEN_SYSTEM = []


def model(messages, specs, max_tokens=500, **kw):
    """A scripted stand-in for the provider: picks a tool from what it was offered, and answers once results are in."""
    MODEL_CALLS.append(messages[-1]["role"])
    SEEN_SYSTEM.append(messages[0]["content"])
    offered = {s["function"]["name"] for s in specs}
    if messages[-1]["role"] == "tool":
        last = messages[-1]["content"]
        return {"text": "The file says: meeting at five." if "Meeting at five" in last else "", "calls": [], "provider": "groq"}
    user = messages[-1]["content"].lower()
    rules = [("remember", "remember", {"fact": "my exam is on friday", "key": "exam"}), ("translate", "translate", {"text": "good morning", "language": "hindi"}),
             ("play", "play_media", {"query": user}), ("note", "take_note", {"text": "buy milk", "topic": "shopping"}),
             ("notes for", "search_docs", {"query": "graphs"}), ("search my notes", "search_docs", {"query": "graphs"}),
             ("in my pictures", "describe_image", {"folder": "pictures", "index": 4, "kind": "pictures", "sort": "name"}),
             ("list", "list_folder", {"folder": "pictures", "sort": "date"}), ("what is in", "list_folder", {"folder": "documents"}),
             ("read the file", "read_text_file", {"path": str(fake_home / "Documents" / "notes.txt")}),
             ("diary", "read_text_file", {"path": str(fake_home / "Documents" / "personal-diary.txt")}),
             ("send this", "send_to_device", {"device": "phone", "what": "this"}), ("send it", "send_to_device", {}),
             ("how is my system", "system_status", {}), ("battery", "battery", {})]
    for word, tool_name, args in rules:
        if word in user and tool_name in offered:
            return {"text": "Done, it is all handled.", "calls": [{"id": "c1", "name": tool_name, "args": args}], "provider": "groq"}
    return {"text": "I am not sure what you mean.", "calls": [], "provider": "groq"}


def chat(text, on_delta=None):
    SEEN_SYSTEM.append(brain.quality_system(text))
    reply = "I run in hybrid mode with cloud brains first."
    if on_delta:
        on_delta(reply)
    return {"action": "chat", "say": reply}


results, lines_by_case = [], {}
spoken = []


def said(text):
    with voice.capture() as lines:
        core.handle(text)
    return " ".join(lines)


def case(name, text, pattern, forbid=None, calls=None):
    before = len(MODEL_CALLS)
    out = said(text)
    ok = bool(re.search(pattern, out, re.I | re.S)) and not (forbid and re.search(forbid, out, re.I))
    if calls is not None:
        ok = ok and len(MODEL_CALLS) - before == calls
    results.append((name, ok, out[:160]))
    return out


with mock.patch.object(brain, "tool_turn", model), mock.patch.object(brain, "chat", chat), mock.patch.object(brain, "ollama_reachable", lambda: True), \
        mock.patch.object(platform, "volume_set"), mock.patch.object(platform, "volume_change"), mock.patch.object(platform, "volume_get", return_value=40), \
        mock.patch.object(platform, "unmute"), mock.patch.object(platform, "clipboard_write", return_value=True), mock.patch.object(platform, "open_target"), \
        mock.patch.object(platform, "clipboard_read", return_value="hello from the clipboard"), mock.patch.object(tools, "read_battery", return_value=(80, "discharging")), \
        mock.patch.object(tools, "_launch"), mock.patch.object(play, "start", return_value="Playing lofi beats."), \
        mock.patch.object(brain, "ask", lambda *a, **k: "सुप्रभात"), mock.patch.object(brain, "look", lambda prompt, jpeg: {"say": "A sunny beach with two people."}), \
        mock.patch.object(screen, "_jpeg", lambda p: b"jpeg"), mock.patch("jarvis.research.live.gather", return_value=[{"title": "Pune weather", "url": "https://example.test", "snippet": "28 degrees and clear"}]), \
        mock.patch("jarvis.research.live.answer", return_value="It is 28 degrees and clear in Pune."), mock.patch.object(apps, "_launch"):
    case("time", "what time is it", r"\d", calls=0)
    case("date", "what's the date today", r"Today is", calls=0)
    case("volume up", "volume up", r"Louder|olume", calls=0)
    case("set volume", "set the volume to 40", r"Volume 40 percent", calls=0)
    case("mute", "mute", r"mut|volume", calls=0)
    case("play", "play lofi music", r"Playing|lofi", forbid=r"failed")
    case("stop with nothing playing", "stop", r"^$", calls=0)
    case("open an app", "open the browser", r"Opening|open", forbid=r"failed|could not")
    case("reminder", "remind me in ten minutes to stretch", r"remind|ten minutes|10 minutes|stretch", forbid=r"failed|could not", calls=0)
    case("note", "take a note to buy milk", r"Noted", forbid=r"failed")
    case("weather", "what's the weather in Pune", r"28 degrees", calls=0)
    case("search notes", "search my notes for graphs", r"graphs|queue|stack", forbid=r"failed")
    case("features", "what can you do", r"can|tools|help|control", calls=0)
    case("file listing", "list my pictures by date", r"Pictures has 6 items", forbid=r"personal")
    first = said("what is in the 4th picture in my pictures folder")
    second = said("yes")
    results.append(("image read: names the file, then describes it", "IMG_0003.jpg" in first and "Look at it" in first and "sunny beach" in second, (first + " | " + second)[:160]))
    case("read a text file", "read the file notes.txt", r"meeting at five")
    case("remember", "remember my exam is on friday", r"exam|remember|noted|kept|got it", forbid=r"failed")
    case("recall", "what do you remember about exam", r"exam|friday")
    held = said("forget exam")
    done = said("yes")
    results.append(("forget asks, then does it", "yes or no" in held.lower() and re.search(r"forgot|forgotten|deleted|removed|gone|done", done, re.I) is not None, (held + " | " + done)[:160]))
    case("system", "how is my system", r"memory|processor|cpu|ram|percent", calls=0)
    case("battery", "battery status", r"80", calls=0)
    case("translate", "translate good morning to hindi", r"सुप्रभात|Hindi|copied")
    case("send to phone", "send this to my phone", r"Saved the text in the phone outbox", forbid=r"failed")
    case("self description", "who are you, are you offline", r"hybrid")
    case("tasks", "task: buy a cable", r"Task saved")

    # 3D models: fake openscad, canned scad, fake slicer
    import types
    import trimesh
    from jarvis.actions import modeler

    def fake_scad(cmd, timeout):
        trimesh.creation.box((30, 20, 10)).export(cmd[cmd.index("-o") + 1])
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    os.environ["SLICER_CMD"] = "true"
    model_patches = [mock.patch.object(modeler, "MODELS", tmp / "models"), mock.patch.object(modeler, "READY", tmp / "models" / "ready"),
                     mock.patch.object(modeler, "SETTLE", 0), mock.patch.object(modeler, "_run", fake_scad),
                     mock.patch.object(brain, "code", lambda *a, **k: "```\ncube([30, 20, 10]);\n```"),
                     mock.patch.object(modeler, "_launch_slicer", lambda argv: types.SimpleNamespace(poll=lambda: None))]
    for p in model_patches:
        p.start()
    if True:
        case("approve with no model does nothing", "this is good", r".*", forbid=r"slicer|Opened")
        case("make a model", "make a 3d model of a box 30 by 20 by 10 mm", r"Built .*version 1.*30 by 20 by 10", forbid=r"failed", calls=0)
        case("revise a model", "make it 5 mm taller", r"version 2", forbid=r"failed", calls=0)
        case("add a hole", "add a hole", r"version 3", forbid=r"failed", calls=0)
        case("model needs a real measurement", "make a 3d model of a stand for my phone", r"measurements of the phone", forbid=r"failed", calls=0)
        case("answer the measurement", "75 by 150 by 8", r"Built", forbid=r"failed", calls=0)
        case("open holo", "open holo", r"hologram is open", forbid=r"failed|not at", calls=0)
        case("show a model", "show the box", r"Showing box.* on the hologram", forbid=r"failed", calls=0)
        case("reset the hologram", "reset the hologram", r"view is reset", forbid=r"failed", calls=0)
        case("close holo", "close holo", r"hologram is closed", forbid=r"failed", calls=0)
        case("approve a model", "let's print it", r"Opened in the slicer\. Printing is yours to start\.", forbid=r"failed", calls=0)
    for p in model_patches:
        p.stop()
    from jarvis import holo
    holo.stop()

    # ---- the rest: truthfulness, privacy and failure behaviour (not part of the 25) ----
    extra = []

    def ex(name, ok, detail=""):
        extra.append((name, bool(ok), str(detail)[:140]))

    out = said("read my diary")
    ex("a denied file is refused and the refusal is one failure sentence", out.startswith("I tried read text file, it failed because") and "secret" not in out, out)
    ex("the model's own 'Done' is not used after a failure", "all handled" not in out)
    from jarvis import traces
    row = traces.load()[-1]
    ex("the trace of a failure keeps route, tool and error", row.get("ok") is False and row.get("tool") == "read_text_file" and row.get("route", "").startswith("agent")
       and "off limits" in row.get("error", "") or "not allowed" in row.get("error", ""), row)
    out = said("list the files in documents")
    ex("a deny listed name is never listed", "personal" not in out and "notes.txt" in (tmp / "x").parent.joinpath("home/Documents/notes.txt").name, out)
    ex("self block says hybrid, not offline", any("hybrid" in s and "NOT offline" in s for s in SEEN_SYSTEM))
    ex("self block names the providers and tool groups", any("Groq" in s and "Tool categories:" in s for s in SEEN_SYSTEM))
    with mock.patch.object(brain, "tool_turn", lambda *a, **k: None), mock.patch.object(brain, "chat", lambda *a, **k: None):
        first = said("tell me about the moon")
        second = said("tell me about the sun")
    ex("no brain: a cause the first time, not the same line again", first != second and "No brain answered" in first and "Still" in second, f"{first} | {second}")
    with mock.patch.object(brain, "tool_turn", lambda messages, specs, max_tokens=1, **kw: {"text": "ok", "calls": [], "provider": "ollama"}):
        out = said("what is in the documents folder")
    ex("offline replies are prefixed", out.startswith("(offline)"), out)
    box = tmp / "outbox" / "phone.txt"
    ex("send to device wrote and verified the line", box.exists() and "hello from the clipboard" in box.read_text(encoding="utf-8"))
    with mock.patch.object(handoff, "outbox", lambda: tmp / "missing" / "deep"), mock.patch("builtins.open", side_effect=OSError("disk full")):
        out = said("send this to my phone")
    ex("a failed write is reported as a failure", "failed" in out.lower() or "could not" in out.lower(), out)
    out = said("send it")
    ex("a missing recipient is asked about once", "phone or your laptop" in out and "failed" not in out, out)
    ex("access: outside home refused", not access.readable("/etc/passwd") and not access.readable(fake_home / ".ssh" / "id_rsa") and access.readable(fake_home / "Documents" / "notes.txt"))


# the briefing with nothing to report makes no brain call and says so in one line
from jarvis.routines import morning
from jarvis import tasks as _tasks
_tasks.save([])
tools.TOOLS["clear_reminders"]["fn"]({})
with mock.patch.object(brain, "ask", side_effect=AssertionError("no model call for an empty briefing")):
    note = morning.build()
ex("an empty briefing is one line and makes no brain call", note["spoken"] == "Nothing scheduled." and note["source"] == "template", note["spoken"])
ex("the briefing has no greeting", not re.search(r"\bgood (?:morning|afternoon|evening)\b", note["text"], re.I))

# all cloud tiers failing: one line with the cause and the reset time, then something different
import requests
bad = requests.Response()
bad.status_code = 429
bad.headers["retry-after"] = "45"
bad._content = json.dumps({"error": {"message": "Rate limit reached for tokens per minute"}}).encode()
said_lines = []
brain._busy.clear()
brain._outage.update(said=False, no_brain=False)
brain.FAILED.clear()
brain.begin_turn()
with mock.patch.dict(os.environ, {"GROQ_API_KEY": "gsk-x"}), mock.patch.object(brain._http, "post", lambda *a, **k: bad), \
        mock.patch.object(brain, "_ensure_ollama", lambda: False), mock.patch.object(voice, "say", lambda t, *a, **k: said_lines.append(str(t))):
    got, who = brain.route([{"role": "user", "content": "hi"}], 50, want_json=False)
    routed_said = list(said_lines)
    first = brain.outage_line()
    again = brain.outage_line()
    brain.begin_turn()
    second = brain.outage_line()
ex("all cloud tiers failing says nothing inside route, the no-brain line says it once per turn", got is None and not routed_said and again == "", f"{routed_said} | {again}")
ex("the no-brain line names the cause and the reset time the first time and is shorter after", "rate limited" in first and "resets in about 4" in first and first != second and len(second) < len(first), f"{first} | {second}")
brain._busy.clear()

for p in patches:
    p.stop()

passed = sum(1 for _, ok, _ in results if ok)
for name, ok, out in results:
    print(("ok   " if ok else "FAIL ") + name + ("" if ok else f"  -> {out}"))
for name, ok, out in extra:
    print(("ok   " if ok else "FAIL ") + "[extra] " + name + ("" if ok else f"  -> {out}"))
print(f"\ncore phrases: {passed} of {len(results)} passed")
if "--scratch" not in sys.argv:
    out_file = ROOT / "data" / "core-check.json"
    out_file.parent.mkdir(exist_ok=True)
    out_file.write_text(json.dumps({"passed": passed, "total": len(results), "at": time.strftime("%Y-%m-%d %H:%M")}), encoding="utf-8")
bad = passed != len(results) or len(results) < 25 or not all(ok for _, ok, _ in extra)
sys.exit(1 if bad else 0)
