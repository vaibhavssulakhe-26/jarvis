"""The 30 eval phrases and a probe that runs one of them through the real router. Shared by scripts/eval_phrases.py,
jarvis/bench.py and scripts/replay_failures.py. Local tools never run; by default the brain is a mock."""
import re
import time
from unittest import mock

from .actions import events, tools  # noqa: F401
from .brain import brain
from .core import main

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


_real_route = brain.route


def spy_route(messages, max_tokens=500, want_json=True, local=False):
    entry = {"messages": messages, "json": want_json}
    calls.append(entry)
    text, who = _real_route(messages, max_tokens, want_json, local)
    entry["provider"] = who or "none"
    return text, who


def run_one(text, setup="", live=False):
    """(route, estimated tokens, milliseconds, kind, provider). live=True sends brain requests to the real providers."""
    del calls[:], done[:]
    providers = []
    listener = lambda kind, value: providers.append(value) if kind == "provider" else None  # noqa: E731
    events.listeners.append(listener)
    main.PENDING.clear()
    brain.RECENT[:] = []
    brain.LAST_ACTION[0] = None
    mpv = setup == "mpv"
    patches = [mock.patch.object(brain.memory, "context", return_value=""),
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
    if live:
        patches.append(mock.patch.object(brain, "route", spy_route))
    else:
        patches.append(mock.patch.object(brain, "route", fake_route))
    for p in patches:
        p.start()
    t0 = time.perf_counter()
    try:
        main._handle(text)
    finally:
        ms = (time.perf_counter() - t0) * 1000
        for p in patches:
            p.stop()
        events.listeners.remove(listener)
    if calls:
        c = calls[0]
        tokens = brain.estimate(c["messages"])
        who = c.get("provider") or (providers[0] if providers else "mock")
        if c["json"]:
            system = c["messages"][0]["content"]
            offered = [n for n in re.findall(r"^- (\w+):", system.split("Actions:")[-1], re.M) if n not in ("ask", "chat", "none")]
            return "tool:" + ",".join(offered), tokens, ms, "tool", who
        return "chat", tokens, ms, "chat", who
    return "local:" + (done[0] if done else "?"), 0, ms, "local", "local"


def judge(want, got, tokens):
    if want.startswith("tool:"):
        return got.startswith("tool:") and want[5:] in got[5:].split(",") and tokens <= TOOL_LIMIT
    if want == "chat":
        return got == "chat" and tokens <= CHAT_LIMIT
    return got == want


