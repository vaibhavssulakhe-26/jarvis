"""Runs sample utterances through the real router with a mocked brain and prints the pass rate.
Nothing is spoken, no tool runs, and all files go to a scratch folder. Run: python scripts/route_check.py"""
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp()
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import files, tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main  # noqa: E402

CHAT_LIMIT = 400
TOOL_LIMIT = 2000
SYSTEM_LIMIT = 300

# (utterance, expected): "local" or "local:<tool>", "chat", "tool:<tool the brain should be offered>"
CASES = [
    ("hello", "chat"),
    ("hey how are you", "chat"),
    ("Can you hear me?", "chat"),
    ("thank you", "chat"),
    ("good night", "chat"),
    ("tell me a joke", "chat"),
    ("who are you", "chat"),
    ("I'm bored", "chat"),
    ("what is the capital of France", "chat"),
    ("what time is it", "local:time_date"),
    ("what's the date today", "local:time_date"),
    ("battery status", "local:battery"),
    ("how's my system", "local:system_status"),
    ("volume up by 10", "local:volume_up"),
    ("set the volume to 40", "local:set_volume"),
    ("mute", "local:mute"),
    ("unmute", "local:unmute"),
    ("brightness down", "local:brightness"),
    ("take a screenshot", "local:screenshot"),
    ("close firefox", "local:close_app"),
    ("switch to terminal", "local:switch_app"),
    ("change your voice", "local:change_voice"),
    ("use a male voice", "local:change_voice"),
    ("turn on focus guard", "local:guard_switch"),
    ("turn off the clipboard monitor", "local:clip_monitor_switch"),
    ("remind me to stretch in ten minutes", "local:set_reminder"),
    ("remind me in 5 minutes to call mom", "local:set_reminder"),
    ("remind me to drink water every 30 minutes", "local:set_reminder"),
    ("remind me to study at 7 pm", "local:set_reminder"),
    ("list my reminders", "local:list_reminders"),
    ("summarise the project report", "local:summarise_file"),
    ("research solar panels", "local:research_topic"),
    ("build me a todo app in python", "local:build_project"),
    ("yes", "local:pending"),
    ("no", "local:pending"),
    ("find my resume file", "tool:find_file"),
    ("where did I save my thesis", "tool:find_file"),
    ("what hackathons are happening this month", "tool:research"),
    ("draft an email to my professor about the deadline", "tool:draft_text"),
    ("message mom that I will be late", "tool:message_contact"),
    ("play some jazz on youtube", "local:play_media"),
    ("write a python script that renames my files", "local:build_project"),
]

calls = []


def fake_route(messages, max_tokens=500, want_json=True, local=False):
    calls.append({"messages": messages, "json": want_json})
    return ('{"action": "chat", "say": "ok"}' if want_json else "ok"), "mock"


done = []


def classify(text):
    del calls[:]
    del done[:]
    main.PENDING.clear()
    brain.LAST_ACTION[0] = None
    if text in ("yes", "no"):
        main.PENDING.update({"action": "battery", "args": {}, "until": time.time() + 60})
    with mock.patch.object(brain, "route", fake_route), \
            mock.patch.object(brain.memory, "context", return_value=""), \
            mock.patch.object(main, "do_tool", lambda a, args, spoken="": done.append(a)), \
            mock.patch.object(main, "run_tool", lambda a, args, spoken: done.append(a)), \
            mock.patch.object(main.voice, "say", lambda *a, **k: None), \
            mock.patch.object(main.reminders, "active", return_value=None), \
            mock.patch.object(main.apps, "find_app", return_value="app"), \
            mock.patch.object(main.brain, "_history", []):
        main._handle(text)
    if calls:
        c = calls[0]
        system = c["messages"][0]["content"]
        offered = re.findall(r"^- (\w+):", system.split("Actions:")[-1], re.M) if c["json"] else []
        offered = [n for n in offered if n not in ("ask", "chat", "none")]
        tokens = brain.estimate(c["messages"])
        if c["json"]:
            return "tool", offered, tokens, brain.estimate(c["messages"][:1])
        return "chat", [], tokens, brain.estimate(c["messages"][:1])
    if text in ("yes", "no"):
        return "local", ["pending"], 0, 0
    return "local", done[:1], 0, 0


bad = []
worst = {"chat": 0, "tool": 0, "system": 0}
for text, want in CASES:
    kind, names, tokens, system = classify(text)
    if kind == "local":
        got = "local:" + (names[0] if names else "?")
        ok = want == got or want == "local"
    elif kind == "chat":
        got, ok = "chat", want == "chat" and tokens <= CHAT_LIMIT
        worst["chat"] = max(worst["chat"], tokens)
        worst["system"] = max(worst["system"], system)
        ok = ok and system <= SYSTEM_LIMIT
    else:
        got = "tool:" + ",".join(names)
        ok = want.startswith("tool:") and want[5:] in names and len(names) <= 5 and tokens <= TOOL_LIMIT
        worst["tool"] = max(worst["tool"], tokens)
    if not ok:
        bad.append((text, want, got, tokens))
    print(("ok   " if ok else "FAIL ") + f"{text!r:55} {got}" + (f"  ~{tokens} tokens" if tokens else ""))

print(f"\npass rate: {len(CASES) - len(bad)}/{len(CASES)} ({100 * (len(CASES) - len(bad)) // len(CASES)}%)")
print(f"largest chat request ~{worst['chat']} tokens (system prompt ~{worst['system']}), largest tool request ~{worst['tool']}")
for text, want, got, tokens in bad:
    print(f"misroute: {text!r} wanted {want}, got {got} (~{tokens} tokens)")
sys.exit(1 if bad else 0)
