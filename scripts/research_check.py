"""Checks research mode with sample HTML, mocked search and brain. No network. Run: python scripts/research_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-research-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")

from jarvis.actions import tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.memory import notes  # noqa: E402
from jarvis.research import research, topic  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name)


ARTICLE = ("<html><head><title>Graphs</title><script>var x=1;</script></head><body><nav>menu home about</nav>"
           "<article><h1>Graph basics</h1>" + "<p>A graph has nodes and edges. Breadth first search walks it level by level "
           "using a queue, while depth first search goes deep using a stack. Graphs model roads and networks.</p>" * 4 +
           "</article><footer>cookie banner</footer></body></html>")
PAGES = {f"https://site{i}.org/graphs": ARTICLE for i in range(5)}
PAGES["https://site2.org/graphs"] = ""
hits = [{"href": u, "title": f"Page {i}", "body": "graphs"} for i, u in enumerate(PAGES)]
FINAL = "SAY: Graphs link nodes with edges. BFS uses a queue. DFS uses a stack.\nNOTE:\n- Graphs have nodes [1]\n- BFS uses a queue [2]"
calls = []


def fake_ask(prompt, max_tokens=0, system=None, cache=False, local=False):
    calls.append(system or "")
    if system == topic.FINAL_SYSTEM:
        return FINAL
    if system == topic.ROUTE_SYSTEM:
        return "RESEARCH" if "graph" in prompt else "HOWTO"
    return "A short page summary."


check("main text drops menus and scripts", "menu home" not in topic.main_text(ARTICLE) and "queue" in topic.main_text(ARTICLE))
clip, opened = [], []
patches = (mock.patch.object(research, "_search", return_value=hits),
           mock.patch.object(topic, "fetch_html", side_effect=lambda u: PAGES[u]),
           mock.patch.object(topic.voice, "say"), mock.patch.object(topic.time, "sleep"),
           mock.patch.object(topic, "write_clip", side_effect=lambda t: clip.append(t) or True),
           mock.patch.object(topic, "_browser", side_effect=opened.append),
           mock.patch.object(brain, "ask", side_effect=fake_ask))
for p in patches:
    p.start()
out = tools.TOOLS["research_topic"]["fn"]({"topic": "Graph theory"})
check("speaks the short answer", out.startswith("Graphs link nodes") and "[" not in out)
check("at most 6 brain calls", len(calls) <= 6)
check("failed page is skipped", len(clip[0].splitlines()) == 4 and "site2" not in clip[0])
note = (notes.NOTES_DIR / "research-graph-theory.md").read_text()
check("note has citations and sources", "[2]" in note and "site4.org" in note)
check("note stays in the temp data folder", str(notes.NOTES_DIR).startswith(str(tmp)))
before = len(calls)
tools.TOOLS["research_topic"]["fn"]({"topic": "graph theory"})
check("second request is served from the cache", len(calls) == before)
tools.TOOLS["open_sources"]["fn"]({})
check("sources open in the browser", len(opened) == 3 and opened[0].startswith("https://site0"))

calls.clear()
topic._cache.clear()
tools.TOOLS["help_topic"]["fn"]({"topic": "graph algorithms"})
check("help on a factual topic runs research", len(calls) <= 6 and topic.FINAL_SYSTEM in calls)
calls.clear()
hits[:] = [{"href": "https://docs.python.org/3/library/venv.html", "title": "venv", "body": ""},
           {"href": "https://blog.example.net/venv", "title": "blog", "body": ""}]
out = tools.TOOLS["help_topic"]["fn"]({"topic": "how do I make a venv"})
check("how-to opens the docs page", opened[-1] == "https://docs.python.org/3/library/venv.html" and "docs.python.org" in out)
check("how-to uses two calls", len(calls) == 2)
for p in patches:
    p.stop()
print("failures:", results.count(False))
sys.exit(1 if False in results else 0)
