"""Checks usage logging, 'jarvis stats' and the eval script (run in a scratch folder). Run: python scripts/stats_check.py"""
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

scratch = Path(tempfile.mkdtemp(prefix="jarvis-stats-"))
os.environ["JARVIS_DATA"] = str(scratch)
os.environ["XDG_STATE_HOME"] = str(scratch)
os.environ["XDG_RUNTIME_DIR"] = str(scratch)
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import stats  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


msgs = [{"role": "user", "content": "x" * 400}]
brain.log_usage("groq", msgs, "y" * 40)
brain.log_usage("groq", msgs, "y" * 40)
brain.log_usage("ollama", msgs, "z")
usage = json.loads((scratch / "usage.json").read_text())
today = datetime.now().strftime("%Y-%m-%d")
check("usage counts calls and tokens per provider", usage[today]["groq"]["calls"] == 2 and usage[today]["groq"]["tokens"] == 2 * (brain.estimate(msgs) + 10)
      and usage[today]["ollama"]["calls"] == 1, str(usage))
check("usage never stores any text", "xxxx" not in (scratch / "usage.json").read_text())

fake = [("groq", lambda m, t, j: ('{"action":"chat","say":"hi"}', 200)), ("openrouter", lambda m, t, j: (None, 0)), ("ollama", lambda m, t, j: (None, 0))]
before = json.loads((scratch / "usage.json").read_text())[today]["groq"]["calls"]
with mock.patch.object(brain, "PROVIDERS", tuple(fake)), mock.patch.object(brain, "_room", lambda n, t: True):
    brain._busy.clear()
    brain.route([{"role": "user", "content": "hi"}])
check("route logs the provider that answered", json.loads((scratch / "usage.json").read_text())[today]["groq"]["calls"] == before + 1)

old = {f"2026-01-{d:02d}": {"groq": {"calls": 1, "tokens": 1}} for d in range(1, 31)}
(scratch / "usage.json").write_text(json.dumps(old))
brain.log_usage("groq", msgs, "")
check("only the last 30 days are kept", len(json.loads((scratch / "usage.json").read_text())) == 30)
(scratch / "usage.json").write_text("garbage")
brain.log_usage("groq", msgs, "")
check("a damaged usage file starts over", json.loads((scratch / "usage.json").read_text())[today]["groq"]["calls"] == 1)

week, day = stats.usage()
check("usage sums the week and returns today", week["groq"]["calls"] == 1 and day["groq"]["calls"] == 1)

proc = subprocess.run([sys.executable, str(root / "scripts" / "eval_phrases.py"), "--scratch"], capture_output=True, text=True, timeout=120, cwd=root)
check("the eval script passes all 30 phrases", proc.returncode == 0 and "30/30 passed" in proc.stdout, proc.stdout[-300:] + proc.stderr[-300:])
m = [l for l in proc.stdout.splitlines() if l.startswith("saved ")]
saved = Path(m[0][6:]) if m else None
data = json.loads(saved.read_text()) if saved and saved.exists() else {}
check("the eval result is saved as data/eval/<date>.json", saved and saved.name == f"{today}.json" and data.get("total") == 30 and len(data.get("results", [])) == 30)
check("each result has tokens and time", all({"phrase", "pass", "tokens", "ms"} <= set(r) for r in data.get("results", [])))
check("eval writes to a scratch folder with --scratch, not data/", saved and str(root / "data") not in str(saved))

(scratch / "eval").mkdir()
(scratch / "eval" / f"{today}.json").write_text(json.dumps({"date": today, "total": 30, "passed": 29, "avg_tokens": 321, "avg_ms": 1.2, "results": []}))
(scratch / "usage.json").write_text(json.dumps({today: {"groq": {"calls": 12, "tokens": 6000}, "ollama": {"calls": 1, "tokens": 300}}}))
spoken, full = stats.build()
check("stats speaks the pass rate and tokens", "29 of 30" in spoken and "97 percent" in spoken and "321 tokens" in spoken, spoken)
check("stats speaks the provider counts", "Groq answered 12" in spoken and "OpenRouter answered 0" in spoken and "Ollama answered 1" in spoken, spoken)
check("the screen text has a line per provider", all(name in full for name in ("Groq", "OpenRouter", "Ollama")), full)
ran = []
with mock.patch.object(main, "run_tool", lambda a, args, s: ran.append(a)):
    for phrase in ("jarvis stats", "stats", "show me stats"):
        main.direct(phrase)
check("'jarvis stats' routes locally", ran == ["jarvis_stats"] * 3, str(ran))
sys.exit(1 if bad else 0)
