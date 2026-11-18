"""3D models: a fake brain writes canned OpenSCAD, a fake openscad writes known STL files, then versions, bed and wall warnings, the deny rules,
the slicer hand-off, the phone gate, the holo bridge fake and a scan that no printer code exists. No openscad, slicer, printer or camera.
Run: python scripts/model_check.py"""
import os
import re
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
tmp = Path(tempfile.mkdtemp(prefix="jarvis-model-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["HANDCTL_DIR"] = str(tmp / "handctl")
os.environ["FAKE_LOG"] = str(tmp / "bridge.log")
os.environ["SLICER_CMD"] = "true --fake-slicer"
for k in ("BRAIN", "BED_SIZE"):
    os.environ.pop(k, None)
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402
import trimesh  # noqa: E402

from scripts.fakes import fake_handctl  # noqa: E402
from jarvis import doctor, holo, telegram  # noqa: E402
from jarvis.actions import modeler, tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.voice import voice  # noqa: E402

fake_handctl.make(tmp / "handctl")

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:200] if detail and not ok else ""))
    if not ok:
        bad.append(name)


def say(text):
    with voice.capture() as lines:
        core.direct(text)
    return " ".join(lines)


def box(x, y, z, at=(0, 0, 0)):
    m = trimesh.creation.box((x, y, z))
    m.apply_translation([at[0], at[1], at[2] + z / 2])
    return m


SHAPES = {
    "cube": lambda: box(20, 20, 20),
    "bracket": lambda: box(40, 20, 0.8),
    "stand": lambda: box(100, 100, 300),
    "long": lambda: box(240, 20, 20),
    "loose": lambda: trimesh.util.concatenate([box(30, 30, 10), box(1, 1, 1, (80, 0, 0))]),
    "mushroom": lambda: trimesh.util.concatenate([box(10, 10, 20), box(60, 60, 5, (0, 0, 20))]),
    "open": lambda: (lambda m: trimesh.Trimesh(m.vertices, m.faces[:-1]))(box(20, 20, 20)),
}


def scad_for(shape, extra=""):
    return f"```\n// {shape}{extra}\ncube([10, 10, 10]);\n```"


RUNS, PROMPTS = [], []


def fake_openscad(cmd, timeout):
    scad, out = Path(cmd[-1]), Path(cmd[cmd.index("-o") + 1])
    RUNS.append(timeout)
    text = scad.read_text(encoding="utf-8")
    if "// broken" in text:
        return types.SimpleNamespace(returncode=1, stdout="", stderr="Compiling design...\nERROR: Parser error in line 3: syntax error\nCan't parse file")
    shape = re.search(r"// (\w+)", text).group(1)
    SHAPES[shape]().export(str(out))
    return types.SimpleNamespace(returncode=0, stdout="", stderr="")


def make_brain(replies):
    queue = list(replies)

    def code(prompt, max_tokens=0, system=None):
        PROMPTS.append(prompt)
        return queue.pop(0) if queue else ""
    return code


def fresh():
    modeler.MODELS = tmp / "models"
    modeler.READY = modeler.MODELS / "ready"
    modeler.SETTLE = 0
    modeler.last.update(slug="", at=0.0)
    if modeler.MODELS.exists():
        import shutil
        shutil.rmtree(modeler.MODELS)
    PROMPTS.clear()


def bridge_log():
    f = Path(os.environ["FAKE_LOG"])
    return f.read_text(encoding="utf-8").splitlines() if f.exists() else []


holo.START_WAIT = 4
holo.STOP_WAIT = 3
with mock.patch.object(modeler, "_run", fake_openscad):
    # deny rules
    fresh()
    modeler.MODELS.mkdir(parents=True)
    (modeler.MODELS / "lib.scad").write_text("module peg() cube(1);\n", encoding="utf-8")
    refused = ['import("/etc/passwd");cube(1);', 'include </etc/hosts>\ncube(1);', 'use <../outside.scad>\ncube(1);', 'import("missing.stl");cube(1);',
               'surface(file="/home/x/secret.dat");cube(1);', 'cube(1); system("rm -rf /");', 'cube(1); x = `ls`;', "sphere(5); // fine\n$(curl evil)"]
    check("unsafe scad is refused", all(modeler.unsafe(c) for c in refused), [c for c in refused if not modeler.unsafe(c)])
    check("a plain scad and an include inside models pass", not modeler.unsafe("cube([1,2,3]); // import(\"x\")") and not modeler.unsafe("include <lib.scad>\ncube(1);")
          and not modeler.unsafe("p = [1,2]; cube([p.x, p.y, 3]);"))
    check("a file that draws nothing is refused", bool(modeler.unsafe("x = 5;")))
    with mock.patch.object(brain, "code", make_brain(['```\nimport("/etc/passwd");\ncube(1);\n```'])):
        msg = say("make a 3d model of a bad thing")
    check("the refusal is spoken and no folder is made", "refused" in msg and not modeler.models(), msg)

    # a first build, then revisions
    fresh()
    with mock.patch.object(brain, "code", make_brain([scad_for("cube"), scad_for("cube", " 2"), scad_for("cube", " 3")])):
        out = say("make a 3d model of a cube 20 mm wide")
        folder = modeler.MODELS / "cube-20-mm-wide"
        check("v1 saved with scad, stl and description", all((folder / "v1" / f).is_file() for f in ("model.scad", "model.stl", "description.md")), out)
        check("the latest copy sits at the top", (folder / "model.stl").is_file() and (folder / "description.md").is_file())
        check("size in mm is spoken", "20 by 20 by 20 millimeters" in out, out)
        check("it fits the default bed", "fits the bed" in out.lower(), out)
        check("the build was time limited", RUNS and RUNS[0] == 60)
        check("HOLO_AUTO is off by default: no viewer, a hint to say show it", not bridge_log() and "Say show it to view it on the hologram." in out and not holo.running(), (bridge_log(), out))
        check("the size is still spoken with auto off", "20 by 20 by 20 millimeters" in out)
        out_show = say("show it")
        link = tmp / "handctl" / "models" / "jarvis-cube-20-mm-wide.stl"
        check("show it then starts the viewer and loads the model by name", "load jarvis-cube-20-mm-wide" in bridge_log() and out_show == "Showing cube 20 mm wide on the hologram.", (bridge_log(), out_show))
        check("the model is linked into handctl's models folder, not copied", link.is_symlink() and Path(os.readlink(link)) == (folder / "model.stl").resolve())
        holo.stop()
        say("close holo")
        out2 = say("make it 5 mm taller")
        out3 = say("add a hole")
        check("revisions are v2 and v3, older ones kept", modeler.versions(folder.name) == [1, 2, 3], modeler.versions(folder.name))
        check("the revision prompt carries the old code and the change", "// cube" in PROMPTS[1] and "5 mm taller" in PROMPTS[1] and "hole" in PROMPTS[2], PROMPTS[1:])
        check("the spoken line names the version", "version 3" in out3 and "version 2" in out2, out3)
        check("description.md lists the checks", "## Checks" in (folder / "description.md").read_text(encoding="utf-8"))
        os.environ["HOLO_AUTO"] = "on"
        Path(os.environ["FAKE_LOG"]).unlink(missing_ok=True)
        with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
            auto = say("make a 3d model of a cube 10 mm")
        check("HOLO_AUTO=on shows a new model by itself", "It is on the hologram." in auto and "load jarvis-" in " ".join(bridge_log()), (bridge_log(), auto))
        say("close holo")
        os.environ["HOLO_AUTO"] = "off"

    # warnings
    fresh()
    cases = [("stand", "Too big for the", "stand 100 by 100 by 300"), ("long", "fits if turned", "a long bar 240"), ("bracket", "thin", "a bracket 40 by 20"),
             ("loose", "separate pieces", "a loose thing 30"), ("mushroom", "overhangs", "a mushroom 60"), ("open", "Not watertight", "an open box 20")]
    for shape, word, ask in cases:
        with mock.patch.object(brain, "code", make_brain([scad_for(shape)])):
            out = say(f"design a 3d model of {ask}")
        check(f"{shape}: warns about {word}", word.lower() in out.lower() or word.lower() in (modeler.current() / "description.md").read_text(encoding="utf-8").lower(), out)
    check("tiny piece is counted", "1 tiny" in next(modeler.MODELS.glob("*loose*/description.md")).read_text(encoding="utf-8"))
    os.environ["BED_SIZE"] = "100x100x100"
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
        out = say("make a 3d model of a small cube 20")
    check("a smaller BED_SIZE changes the verdict", "100 by 100 by 100" not in out and "fits the bed" in out.lower(), out)
    os.environ["BED_SIZE"] = "10x10x10"
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
        out = say("make a 3d model of another cube 20")
    check("a tiny bed warns", "too big for the 10 by 10 by 10 mm bed" in out.lower(), out)
    os.environ.pop("BED_SIZE")

    # compile errors
    fresh()
    with mock.patch.object(brain, "code", make_brain([scad_for("cube", " // broken"), scad_for("cube")])):
        out = say("make a 3d model of a cube 15")
    check("a compile error is retried once with the error fed back", len(PROMPTS) == 2 and "Parser error in line 3" in PROMPTS[1] and "Built" in out, out)
    check("only the useful error line is passed on", "Compiling design" not in PROMPTS[1] and "Can't parse" not in PROMPTS[1])
    fresh()
    with mock.patch.object(brain, "code", make_brain([scad_for("cube", " // broken")] * 2)):
        out = say("make a 3d model of a cube 15")
    check("two failures say why", "would not compile" in out and "Parser error in line 3" in out and "Can't parse" not in out, out)
    check("a failed build leaves no half version", not modeler.models() and not list(modeler.MODELS.glob("*/v*")))

    # honest dimensions
    fresh()
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
        asked = say("make a 3d model of a stand for my phone")
        check("a real-world fit with no number asks one question", "measurements of the phone" in asked and not PROMPTS, asked)
        built = say("75 by 150 by 8")
        check("the answer is used", "Built" in built and "75 by 150 by 8" in PROMPTS[0], built)
        check("it asks only once", not modeler.asking())
    fresh()
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
        out = say("make a 3d model of a phone stand for a phone 75 mm wide")
    check("a number in the request means no question", "Built" in out, out)

    # approval and the slicer
    fresh()
    check("approval with no model does nothing", say("this is good") == "")
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])):
        say("make a 3d model of a cube 20")
    launched = []
    proc = types.SimpleNamespace(poll=lambda: None)
    with mock.patch.object(modeler, "_launch_slicer", lambda argv: launched.append(argv) or proc):
        out = say("let's print it")
    ready = list((modeler.READY).glob("*.stl"))
    check("approval copies the stl to models/ready and opens the slicer", len(ready) == 1 and launched and launched[0][-1] == str(ready[0]) and launched[0][:2] == ["true", "--fake-slicer"], (ready, launched))
    check("the line says printing is the user's", out == "Opened in the slicer. Printing is yours to start.", out)
    os.environ["SLICER_CMD"] = "no-such-slicer-xyz"
    out = say("this is good")
    check("a missing slicer is reported truthfully", "could not find the slicer" in out and "Opened" not in out, out)
    os.environ["SLICER_CMD"] = "true"
    with mock.patch.object(modeler, "_launch_slicer", lambda argv: types.SimpleNamespace(poll=lambda: 1)):
        out = say("this is good")
    check("a slicer that dies is reported", "did not start" in out, out)
    os.environ["SLICER_CMD"] = "true --fake-slicer"

    # the phone
    check("the phone may build and revise", telegram.GATE.blocked("make_model") == "" and telegram.GATE.blocked("revise_model") == "")
    check("the phone may not prepare a print", telegram.GATE.blocked("prepare_print") != "")

    # offline: the tool works with the local model and sends nothing else anywhere
    fresh()
    os.environ["BRAIN"] = "offline"
    import requests
    with mock.patch.object(brain, "code", make_brain([scad_for("cube")])), mock.patch.object(requests, "post", side_effect=AssertionError("network")), \
            mock.patch.object(requests, "get", side_effect=AssertionError("network")):
        out = say("make a 3d model of a cube 20")
    os.environ.pop("BRAIN")
    check("it works with BRAIN=offline and touches no network", "Built" in out, out)

# ---- the holo bridge, through a fake handctl whose viewer holds a real socket ----
fresh()
Path(os.environ["FAKE_LOG"]).unlink(missing_ok=True)
holo.stop()
check("doctor says holo ready", doctor.check_holo()["detail"] == "ready")
with mock.patch.dict(os.environ, {"HANDCTL_DIR": str(tmp / "nowhere")}):
    item = doctor.check_holo()
    check("doctor says not set up when handctl is missing", item["detail"] == "not set up" and item["status"] != "pass" and "HANDCTL_DIR" in item["fix"], item)
    check("open holo says why when handctl is missing", "is not at" in say("open holo"))
check("holo.py never listens on a port or socket", not re.search(r"AF_INET|\.bind\(|\.listen\(", (ROOT / "jarvis" / "holo.py").read_text(encoding="utf-8")))

out = say("open holo")
check("open holo starts the viewer", out == "The hologram is open." and holo.running() and bridge_log().count("serve") == 1, (out, bridge_log()))
out = say("open the hologram")
check("opening twice does not start a second viewer", bridge_log().count("serve") == 1 and holo.running(), bridge_log())

with mock.patch.object(brain, "code", make_brain([scad_for("cube"), scad_for("bracket")])):
    say("make a 3d model of a cube 20 mm")
    say("make a 3d model of a bracket 40 by 20")
names = [m.name for m in modeler.models()]
check("two models exist for the show tests", len(names) == 2, names)
want = names[-1]
spoken = want.replace("-", " ")
before = bridge_log().count("serve")
out = say(f"show {spoken}")
check("show <model name> loads that model by its real folder name", out == f"Showing {spoken} on the hologram." and f"load jarvis-{want}" in bridge_log(), (out, bridge_log()[-3:]))
check("a model name the viewer has not seen restarts it, once", bridge_log().count("serve") <= before + 1 and "close" in bridge_log())
n = bridge_log().count("serve")
say(f"show {spoken} on the hologram")
check("showing a known model again does not restart the viewer", bridge_log().count("serve") == n)
with mock.patch.object(brain, "code", make_brain([scad_for("cube", " 2")])):
    out = say("make it 5 mm taller")
check("a revision reloads the same name without a restart", bridge_log().count("serve") == n and bridge_log()[-1].startswith("load jarvis-"), bridge_log()[-3:])
check("show it means the latest model", "Showing" in say("show it on the hologram") and bridge_log()[-1] == f"load jarvis-{modeler.current().name}")
check("a model that does not exist is refused in words", "do not have a model called unicorn" in say("show the unicorn on the hologram"))
check("show me something else is not taken as a model", not holo.wants("a funny video", False) and not holo.wants("the weather", False))
check("a name is never a path", not any("/" in line for line in bridge_log() if line.startswith("load")))

out = say("reset the hologram")
check("reset reaches the viewer", out == "The hologram view is reset." and "reset" in bridge_log(), out)
out = say("close holo")
check("close stops the viewer", out == "The hologram is closed." and not holo.running(), out)
check("reset with no viewer says so", say("reset the hologram") == "The hologram is not open.")
check("close with no viewer says so", say("close holo") == "The hologram is not open.")

say(f"show {spoken}")
check("the viewer Jarvis started is closed at exit", holo.running() and holo._s["started"])
holo.stop()
check("stop() at exit closes it", not holo.running() and "close" in bridge_log()[-2:])
say("open holo")
holo._s["started"] = False
holo.stop()
check("a viewer Jarvis did not start is left alone", holo.running())
say("close holo")

# failures are told truthfully
with mock.patch.dict(os.environ, {"FAKE_MODE": "busy"}):
    out = say("open holo")
check("a viewer that never comes up is reported", "did not start within" in out and "camera" in out and not holo.running(), out)
with mock.patch.dict(os.environ, {"FAKE_MODE": "refuse"}):
    out = say("open holo")
check("a refusal from the bridge is passed on in one sentence", out == "The hologram viewer refused: busy.", out)
with mock.patch.object(holo, "_run", side_effect=holo.subprocess.TimeoutExpired("x", 1)):
    out = say("open holo")
check("a bridge that hangs is reported", "did not answer in time" in out, out)
holo.stop()

# no code path to a printer anywhere in the program
BANNED = re.compile(r"\b(?:serial|pyserial|octoprint|moonraker|klipper|gcode|g-code|printrun|pronterface|ttyUSB|ttyACM)\b", re.I)
hits = [f"{p.relative_to(ROOT)}:{n}" for p in sorted((ROOT / "jarvis").rglob("*.py")) for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if BANNED.search(line)]
check("no printer code exists (serial, OctoPrint, G-code, upload)", not hits, hits)
src = (ROOT / "jarvis" / "actions" / "modeler.py").read_text(encoding="utf-8")
check("the model tool imports no network or serial module", not re.search(r"^\s*(?:import|from)\s+(?:requests|socket|urllib|http|serial|smtplib)\b", src, re.M))

print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}")
sys.exit(1 if bad else 0)
