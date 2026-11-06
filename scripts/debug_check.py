"""Checks clipboard debugging with a mocked brain and clipboard. Run: python scripts/debug_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-check-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import debug  # noqa: E402
from jarvis.brain import brain  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

reply = "SAY: You forgot to import os. Add the import.\nFIX:\nimport os\nprint(os.getcwd())"
put = []
run = tools.TOOLS["debug_clipboard"]["fn"]
with mock.patch.object(debug, "read_clip", return_value="NameError: name 'os' is not defined"), \
        mock.patch.object(brain, "ask", return_value=reply), \
        mock.patch.object(debug, "write_clip", side_effect=lambda t: put.append(t) or True):
    out = run({"kind": "error"})
check("short answer is spoken", out.startswith("You forgot to import os") and "clipboard" in out)
check("full fix is copied", put == ["import os\nprint(os.getcwd())"])
with mock.patch.object(debug, "read_clip", return_value="api_key = sk-abcdefghijklmnopqrstuv"), \
        mock.patch.object(brain, "ask") as ask:
    try:
        run({"kind": "code"})
        check("secret is refused", False)
    except tools.ToolError:
        check("secret is refused", not ask.called)
with mock.patch.object(debug, "read_clip", return_value=""):
    try:
        run({})
        check("empty clipboard", False)
    except tools.ToolError:
        check("empty clipboard", True)

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

