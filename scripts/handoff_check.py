"""Checks the outbox hand-off in a temp folder. Run: python scripts/handoff_check.py"""
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
from jarvis.actions import handoff  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

run = tools.TOOLS["send_to_device"]["fn"]
check("text", "text" in run({"device": "phone", "what": "buy milk"}))
check("link", "link" in run({"device": "phone", "what": "https://example.com/a"}))
src = tmp / "report.txt"
src.write_text("hello")
check("file", "file" in run({"device": "laptop", "what": str(src)}))
check("file copied", (tmp / "outbox" / "files" / "report.txt").read_text() == "hello")
lines = (tmp / "outbox" / "phone.txt").read_text().splitlines()
check("phone outbox has two lines", len(lines) == 2 and "buy milk" in lines[0])
with mock.patch.object(handoff, "read_clip", return_value="copied words"):
    run({"device": "mobile", "what": "this"})
check("clipboard is used for this", "copied words" in (tmp / "outbox" / "phone.txt").read_text())
for bad in ({"device": "fridge", "what": "x"}, {"device": "phone", "what": "gsk_" + "a1B2c3D4" * 5}):
    try:
        run(bad)
        check("refused " + bad["device"], False)
    except tools.ToolError:
        check("refused " + bad["device"], True)

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

