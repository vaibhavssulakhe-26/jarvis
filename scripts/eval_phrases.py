"""Runs 30 phrases through the real router with a mocked brain: no audio, no network, no tool runs.
Prints pass or fail, estimated tokens and time per phrase, and saves data/eval/<date>.json (read by 'jarvis stats').
Run: python scripts/eval_phrases.py [--scratch]   (--scratch writes the result to a temp folder instead of data/)"""
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp(prefix="jarvis-eval-")
if "--scratch" in sys.argv:
    os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.brain import brain  # noqa: E402
from jarvis.core import config, main  # noqa: E402

CHAT_LIMIT = 400
TOOL_LIMIT = 800

# (category, phrase, expected, setup). expected: "chat", "local:<tool>", "tool:<tool offered to the brain>".
# setup "mpv" pretends mpv is running.
CASES = [
    ("greeting", "hello", "chat", ""),
    ("greeting", "good morning", "local:good_morning", ""),
    ("greeting", "thank you", "chat", ""),
    ("capabilities", "what can you do", "local:capabilities", ""),
    ("capabilities", "help", "local:capabilities", ""),
    ("music", "play lofi beats", "local:play_media", ""),
    ("music", "watch binary search", "local:play_media", ""),
    ("music", "pause", "local:pause_music", "mpv"),
    ("stop", "stop", "local:stop_music", "mpv"),
    ("stop", "stop", "local:stop_speech", ""),
    ("stop", "quiet", "local:pause_music", "mpv"),
    ("notes", "note: buy a usb cable", "local:quick_note", ""),
    ("notes", "search my notes for graphs", "local:search_docs", ""),
    ("notes", "what did I write about arrays", "local:search_docs", ""),
    ("notes", "reindex my notes", "local:reindex_notes", ""),
    ("study", "quiz me on trees", "local:quiz_me", ""),
    ("study", "teach me about recursion", "local:teach_me", ""),
    ("study", "what's next on my roadmap", "local:roadmap_next", ""),
    ("study", "log today", "local:log_today", ""),
    ("study", "start focus 25", "local:start_focus", ""),
    ("reminders", "remind me to stretch in ten minutes", "local:set_reminder", ""),
    ("reminders", "list my reminders", "local:list_reminders", ""),
    ("laptop", "volume up by 10", "local:volume_up", ""),
    ("laptop", "close firefox", "local:close_app", ""),
    ("laptop", "read my screen", "local:read_screen", ""),
    ("laptop", "what's the battery", "local:battery", ""),
    ("translate", "translate good morning to hindi", "local:translate", ""),
    ("research", "research solar panels", "local:research_topic", ""),
    ("research", "what hackathons are happening this month", "tool:research", ""),
    ("coding", "build me a todo app in python", "local:build_project", ""),
]

calls = []
done = []


def fake_route(messages, max_tokens=500, want_json=True, local=False):
    calls.append({"messages": messages, "json": want_json})
    return ('{"action": "chat", "say": "ok"}' if want_json else "ok"), "mock"


def run_one(text, setup):
    del calls[:], done[:]
    main.PENDING.clear()
    brain.RECENT[:] = []
    brain.LAST_ACTION[0] = None
    mpv = setup == "mpv"
    patches = [mock.patch.object(brain, "route", fake_route), mock.patch.object(brain.memory, "context", return_value=""),
               mock.patch.object(main, "do_tool", lambda a, args, spoken="": done.append(a)),
               mock.patch.object(main, "run_tool", lambda a, args, spoken: done.append(a)),
               mock.patch.object(main.voice, "say", lambda *a, **k: None),
               mock.patch.object(main.voice, "stop", lambda: done.append("stop_speech") or True),
               mock.patch.object(main.reminders, "active", return_value=None),
               mock.patch.object(main.apps, "find_app", return_value="app"),
               mock.patch.object(main.mpvctl, "running", lambda: mpv),
               mock.patch.object(main.mpvctl, "playing", lambda: mpv),
               mock.patch.object(main.mpvctl, "stop", lambda: done.append("stop_music")),
               mock.patch.object(main.mpvctl, "pause", lambda on=True: done.append("pause_music")),
               mock.patch.object(main.brain, "_history", [])]
    for p in patches:
        p.start()
    t0 = time.perf_counter()
    try:
        main._handle(text)
    finally:
        ms = (time.perf_counter() - t0) * 1000
        for p in patches:
            p.stop()
    if calls:
        c = calls[0]
        tokens = brain.estimate(c["messages"])
        if c["json"]:
            system = c["messages"][0]["content"]
            offered = [n for n in re.findall(r"^- (\w+):", system.split("Actions:")[-1], re.M) if n not in ("ask", "chat", "none")]
            return "tool:" + ",".join(offered), tokens, ms, "tool"
        return "chat", tokens, ms, "chat"
    return "local:" + (done[0] if done else "?"), 0, ms, "local"


results = []
for category, text, want, setup in CASES:
    got, tokens, ms, kind = run_one(text, setup)
    if want.startswith("tool:"):
        ok = got.startswith("tool:") and want[5:] in got[5:].split(",") and tokens <= TOOL_LIMIT
    elif want == "chat":
        ok = got == "chat" and tokens <= CHAT_LIMIT
    else:
        ok = got == want
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
