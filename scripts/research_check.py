"""Checks research mode with mocked search and brain; the note goes to a temp folder. Run: python scripts/research_check.py"""
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
from jarvis.brain import brain  # noqa: E402
from jarvis.research import research, topic  # noqa: E402
from jarvis.memory import notes  # noqa: E402

results = []


def check(name, ok):
    ok = bool(ok)
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)

hits = [{"href": f"https://example.com/{i}", "title": f"Source {i}", "body": "about graphs"} for i in range(5)]
reply = "SAY: Graphs link nodes with edges. They model networks. BFS and DFS walk them.\nNOTE:\n- Graphs have nodes [1]\n- BFS uses a queue [2]"
calls = []
with mock.patch.object(research, "_search", return_value=hits), mock.patch.object(research, "_page_text", return_value=""), \
        mock.patch.object(topic.voice, "say"), \
        mock.patch.object(brain, "ask", side_effect=lambda *a, **k: calls.append(1) or reply):
    out = tools.TOOLS["research_topic"]["fn"]({"topic": "Graph theory"})
check("speaks the summary", out.startswith("Graphs link nodes") and "[" not in out)
check("one brain call", len(calls) == 1)
note = (notes.NOTES_DIR / "research-graph-theory.md").read_text()
check("note has citations and sources", "[2]" in note and "https://example.com/4" in note)
check("note is under the temp data folder", str(notes.NOTES_DIR).startswith(str(tmp)))

print("failures:", results.count(False))
sys.exit(1 if False in results else 0)

