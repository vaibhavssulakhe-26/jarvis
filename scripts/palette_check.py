"""Checks the command palette hand-off through the shared state file. Run: python scripts/palette_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-check-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import threading  # noqa: E402
import time  # noqa: E402

from jarvis.core import main as core  # noqa: E402
from jarvis.ui import palette  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

check("no assistant running", palette.submit("hello") is False)
got = []
with mock.patch.object(core, "handle", side_effect=got.append):
    threading.Thread(target=core.command_loop, daemon=True).start()
    check("command is picked up", palette.submit("what time is it") is True)
    time.sleep(0.3)
    check("handled once", got == ["what time is it"])
from PyQt6.QtWidgets import QApplication  # noqa: E402
app = QApplication([])
win = palette.Palette()
check("window builds", win.input.placeholderText() == "type a command")

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

