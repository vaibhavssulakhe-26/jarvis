"""Checks the clipboard monitor rules; nothing is read from the real clipboard. Run: python scripts/clipwatch_check.py"""
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
from jarvis.actions import clipwatch  # noqa: E402
from jarvis.core import state  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

kinds = lambda t: (clipwatch.classify(t) or [None])[0]  # noqa: E731
check("link", kinds("https://example.com/post/1") == "link")
check("error", kinds("Traceback (most recent call last):\n  File \"a.py\", line 1\nValueError: bad") == "error")
check("code", kinds("def add(a, b):\n    return a + b\n\nprint(add(1, 2))") == "code")
check("long text", kinds("word " * 150) == "text")
check("short text ignored", kinds("see you at five") is None)
check("api key ignored", kinds("gsk_" + "a1B2c3D4" * 5) is None)
check("password ignored", kinds("password: hunter2hunter2") is None)
check("off by default", clipwatch.enabled() is False)
state.update(clipwatch=True)
check("switch on", clipwatch.enabled() is True)

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

