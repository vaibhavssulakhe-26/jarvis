"""Checks translation with a mocked brain and clipboard. Run: python scripts/translate_check.py"""
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
from jarvis.actions import translate  # noqa: E402
from jarvis.brain import brain  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

clip = []
with mock.patch.object(brain, "ask", return_value="Bonjour"), mock.patch.object(translate, "write_clip", side_effect=lambda t: clip.append(t) or True):
    out = tools.TOOLS["translate"]["fn"]({"text": "hello", "language": "french"})
    check("latin script is spoken", "Bonjour" in out and clip == ["Bonjour"])
with mock.patch.object(brain, "ask", return_value="नमस्ते"), mock.patch.object(translate, "write_clip", side_effect=lambda t: clip.append(t) or True):
    out = tools.TOOLS["translate"]["fn"]({"text": "hello", "language": "hindi"})
    check("other script is copied, not spoken", "नमस्ते" not in out and clip[-1] == "नमस्ते")
with mock.patch.object(translate, "read_clip", return_value=""):
    try:
        tools.TOOLS["translate"]["fn"]({"text": "this", "language": "hindi"})
        check("empty clipboard raises", False)
    except tools.ToolError:
        check("empty clipboard raises", True)

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

