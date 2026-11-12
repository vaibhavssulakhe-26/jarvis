"""Checks the coding helper with a mocked brain, in a temp workspace. Run: python scripts/coder_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-coder-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")

from jarvis.actions import tools  # noqa: E402
from jarvis.actions import coder  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name)


T = tools.TOOLS
calls = []


def fake(prompt, max_tokens=0, system=None):
    calls.append(prompt)
    if "plan a small coding project" in (system or ""):
        return "name: legal portal\nindex.html: the page\nstyle.css: the styles"
    return "```html\n<p>hello</p>\n```"


with mock.patch.object(brain, "code", side_effect=fake), mock.patch.object(coder, "open_in_editor", return_value="VS Code"), \
        mock.patch.object(coder.time, "sleep"):
    out = T["build_project"]["fn"]({"request": "a legal aid portal website"})
folder = tmp / "work" / "legal-portal"
check("plan call then one call per file", len(calls) == 3 and sum("Write the file" in c for c in calls) == 2)
check("files land in the workspace", (folder / "index.html").read_text() == "<p>hello</p>\n" and (folder / "style.css").exists())
check("short result with editor", "Built 2 files" in out and "VS Code" in out)
check("path outside the workspace is refused", not coder.inside("/etc/passwd") and coder.inside(folder / "index.html"))

# edit: summary first, nothing written until yes, then a backup
target = folder / "index.html"
with mock.patch.object(brain, "code", return_value="<p>hello</p>\n<p>footer</p>\n"):
    said = T["edit_file"]["fn"]({"file": "index.html", "change": "add a footer"})
check("edit describes the diff", "1 lines added" in said and "apply" in said)
check("edit waits for a yes", target.read_text() == "<p>hello</p>\n" and core.PENDING.get("action") == "apply_edit")
with mock.patch.object(core.voice, "say"):
    core.check_pending("yes")
check("yes applies the edit", "footer" in target.read_text())
check("backup is kept", Path(str(target) + ".bak").read_text() == "<p>hello</p>\n")
check("confirmation is used up", not core.PENDING)

# bugs: real compile error, fix staged then applied after yes
bad = folder / "app.py"
bad.write_text("def f(:\n    return 1\n")
reply = "CAUSE: There is a stray colon in the argument list.\nFIXED:\ndef f():\n    return 1"
sent = []
with mock.patch.object(brain, "code", side_effect=lambda p, *a, **k: sent.append(p) or reply):
    said = T["find_bugs"]["fn"]({"file": "app.py"})
check("only error and nearby lines are sent", "Errors:" in sent[0] and len(sent[0]) < 600)
check("cause is spoken, fix waits", "stray colon" in said and bad.read_text().startswith("def f(:"))
with mock.patch.object(core.voice, "say"):
    core.check_pending("yeah")
check("fix applied after yes", bad.read_text().startswith("def f():"))
good = folder / "ok.py"
good.write_text("print(1)\n")
check("clean file reports no errors", "no errors" in T["find_bugs"]["fn"]({"file": "ok.py"}))

# run: confirm first, workspace only, sudo refused
check("run asks first", T["run_project"]["risk"] == "confirm" and "ok.py" in T["run_project"]["describe"]({"file": "ok.py"}))
check("run works", "ran fine" in T["run_project"]["fn"]({"file": "ok.py"}) and "Output: 1" in T["run_project"]["fn"]({"file": "ok.py"}))
outside = tmp / "elsewhere.py"
outside.write_text("print(2)\n")
try:
    T["run_project"]["describe"]({"file": str(outside)})
    check("run outside workspace refused", False)
except tools.ToolError:
    check("run outside workspace refused", True)
(folder / "s.py").write_text("import os\nos.system('sudo ls')\n")
try:
    T["run_project"]["describe"]({"file": "s.py"})
    check("sudo refused", False)
except tools.ToolError:
    check("sudo refused", True)
print("failures:", results.count(False))
sys.exit(1 if False in results else 0)
