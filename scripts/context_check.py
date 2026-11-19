"""Pronouns and names: "it", "that", "open that", "show it", "view it in hologram" mean the last model, file or project; model names match loosely
("40mm_cube" finds "40 mm cube"); "can you build a 40 centimeter cube?" goes to the agent with the self block, not a canned answer.
No microphone, hologram, brain or network. Run: python scripts/context_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="jarvis-context-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["HANDCTL_DIR"] = str(tmp / "handctl")
os.environ["FAKE_LOG"] = str(tmp / "bridge.log")
os.environ.pop("BRAIN", None)
sys.path.insert(0, str(ROOT))

import trimesh  # noqa: E402

from scripts.fakes import fake_handctl  # noqa: E402
from jarvis import holo, platform  # noqa: E402
from jarvis.actions import capabilities, modeler, tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core, refs  # noqa: E402
from jarvis.voice import voice  # noqa: E402

fake_handctl.make(tmp / "handctl")
holo.START_WAIT = 4
bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:240] if detail and not ok else ""))
    if not ok:
        bad.append(name)


def say(text, fn=core.direct):
    with voice.capture() as lines:
        got = fn(text)
    return got, " ".join(lines)


def log():
    f = Path(os.environ["FAKE_LOG"])
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


modeler.MODELS = tmp / "models"
modeler.READY = modeler.MODELS / "ready"
modeler.last.update(slug="", at=0.0)
for slug in ("40-mm-cube", "phone-stand"):
    folder = modeler.MODELS / slug
    folder.mkdir(parents=True)
    (folder / "model.scad").write_text("cube(40);\n", encoding="utf-8")
    trimesh.creation.box((40, 40, 40)).export(str(folder / "model.stl"))

# names match loosely
for spoken in ("40mm_cube", "40 mm cube", "40-mm-cube", "40mm cube", "the 40mm_cube", "40 mm cub"):
    found = modeler.match(spoken.replace("the ", ""))
    check(f"{spoken!r} finds the 40 mm cube model", found is not None and found.name == "40-mm-cube", found)
check("an unrelated name finds nothing", modeler.match("bracket") is None and modeler.match("") is None)
check("a phone stand is found with other spacing", modeler.match("phonestand").name == "phone-stand")
load, spoken, src = holo.resolve("40mm_cube")
check("the hologram resolves the loose name too", load == "jarvis-40-mm-cube" and spoken == "40 mm cube" and src.name == "model.stl", (load, spoken))
check("a tool call by loose name works", modeler.current("40mm_cube").name == "40-mm-cube")

# nothing known yet: "open that" is not guessed (the models are made to look old, so the "built in the last hour" rule does not apply)
for slug in ("40-mm-cube", "phone-stand"):
    os.utime(modeler.MODELS / slug / "model.scad", (1.0, 1.0))
refs.forget()
got, out = say("open that")
check("with nothing remembered, open that is left to the other routes", got is False and not out, (got, out))

for slug in ("40-mm-cube", "phone-stand"):
    (modeler.MODELS / slug / "model.scad").touch()
# a model was just made: it, that and the hologram words mean it
refs.remember("model", "40-mm-cube", modeler.MODELS / "40-mm-cube" / "model.stl")
for phrase in ("show it", "view it in hologram", "open that", "show it on the hologram", "view it on the holo", "show that", "pull it up"):
    refs.remember("model", "40-mm-cube", modeler.MODELS / "40-mm-cube" / "model.stl")
    got, out = say(phrase)
    check(f"{phrase!r} shows the last model on the hologram", got is True and "40 mm cube" in out and "hologram" in out, (got, out))
check("the bridge was asked to load that model", any(l == "load jarvis-40-mm-cube" for l in log()), log())
holo.stop()
holo._s["started"] = True
holo.stop()

# a file opened after it is what "that" means; the hologram words still mean the model
opened = []
with mock.patch.object(platform, "open_target", lambda t: opened.append(str(t))):
    refs.remember("file", "notes.txt", tmp / "notes.txt")
    got, out = say("open that")
    check("open that opens the newest thing, a file", got is True and opened == [str(tmp / "notes.txt")] and "notes.txt" in out, (got, out, opened))
    del opened[:]
    got, out = say("view it in hologram")
    check("view it in hologram still means the model", got is True and "40 mm cube" in out and not opened, (got, out, opened))
    refs.remember("project", "todo-app", tmp / "todo-app")
    del opened[:]
    got, out = say("open it")
    check("after a project is built, it means the project folder", got is True and opened == [str(tmp / "todo-app")] and "todo-app" in out, (got, out, opened))
holo.stop()
refs.forget()
with mock.patch.object(refs.time, "time", lambda: 1e12):
    refs.remember("file", "old.txt")
check("a reference older than an hour is forgotten", refs.latest(now=1e12 + 7200) is None and refs.latest(now=1e12 + 60) is not None)
refs.forget()

# capability questions about a real object go to the agent with the self block
check("generic capability questions stay local", capabilities.is_generic_can("can you build apps?") and capabilities.is_generic_can("can you code?"))
got, out = say("can you build apps?")
check("can you build apps is answered from the tool list", got is True and out.startswith("Yes"), (got, out))
seen = []


def fake_turn(messages, specs, max_tokens=0, **kw):
    seen.append(("tool_turn", messages, [s["function"]["name"] for s in specs]))
    return {"text": "Yes. A forty centimeter cube is bigger than the print bed, so I would need it split or scaled.", "calls": [], "provider": "groq"}


def fake_generate(messages, max_tokens, hard=False, on_delta=None, want_json=False, **kw):
    seen.append(("generate", messages, []))
    return "Yes. A forty centimeter cube is bigger than the print bed, so I would need it split or scaled.", "fast"


def fake_chat(text, on_delta=None):
    seen.append(("chat", brain.quality_system(text), []))
    return {"say": "Yes. A forty centimeter cube is bigger than the print bed, so I would need it split or scaled."}


canned = "Yes, I can write, run and fix code"
with mock.patch.object(brain, "tool_turn", fake_turn), mock.patch.object(brain, "generate", fake_generate), \
        mock.patch.object(brain, "_groq_tools", side_effect=AssertionError("network")), mock.patch.object(brain, "_groq_stream", side_effect=AssertionError("network")), \
        mock.patch.object(brain, "route", side_effect=AssertionError("network")):
    got, out = say("can you build a 40 centimeter cube?", core._handle)
check("it is not matched by the canned capability template", canned not in out and not out.startswith("Yes, I can write"), out)
check("a model call was made for it", len(seen) == 1, [s[0] for s in seen])
if seen:
    kind, payload, names = seen[0]
    system = payload if isinstance(payload, str) else " ".join(str(m.get("content")) for m in payload if m.get("role") == "system")
    check("the model saw the self block (mode, brains, tool groups)", "Brains right now" in system and "Mode:" in system and "Tool categories" in system, system[:200])
    check("and answered in its own words", "bigger than the print bed" in out, out)
print("\n" + ("all passed" if not bad else f"{len(bad)} failed"))
sys.exit(1 if bad else 0)
