"""Runs 30 phrases through the real router with a mocked brain: no audio, no network, no tool runs.
Prints pass or fail, estimated tokens and time per phrase, and saves data/eval/<date>.json (read by 'jarvis stats').
Run: python scripts/eval_phrases.py [--scratch]   (--scratch writes the result to a temp folder instead of data/)"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

scratch = tempfile.mkdtemp(prefix="jarvis-eval-")
if "--scratch" in sys.argv:
    os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import evalkit  # noqa: E402
from jarvis.core import config  # noqa: E402

CASES = evalkit.CASES

results = []
for category, text, want, setup in CASES:
    got, tokens, ms, kind, _ = evalkit.run_one(text, setup)
    ok = evalkit.judge(want, got, tokens)
    results.append({"category": category, "phrase": text, "expected": want, "got": got, "pass": ok, "tokens": tokens, "ms": round(ms, 1)})
    print(("pass " if ok else "FAIL ") + f"{category:12} {text!r:46} {got:28} {tokens:5} tok {ms:7.1f} ms")

passed = sum(r["pass"] for r in results)
brain_calls = [r["tokens"] for r in results if r["tokens"]]
summary = {"date": datetime.now().strftime("%Y-%m-%d"), "time": datetime.now().strftime("%H:%M:%S"), "total": len(results), "passed": passed,
           "avg_tokens": round(sum(brain_calls) / len(brain_calls)) if brain_calls else 0,
           "avg_ms": round(sum(r["ms"] for r in results) / len(results), 1), "results": results}
out = config.DATA / "eval"
out.mkdir(parents=True, exist_ok=True)
(out / f"{summary['date']}.json").write_text(json.dumps(summary, indent=1))
print(f"\n{passed}/{len(results)} passed ({100 * passed // len(results)}%), average {summary['avg_tokens']} tokens per brain request, "
      f"{summary['avg_ms']} ms per phrase")
print(f"saved {out / (summary['date'] + '.json')}")
sys.exit(0 if passed == len(results) else 1)
