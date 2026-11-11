"""Runs sample utterances through the real router with a mocked brain and prints the pass rate.
Nothing is spoken, no tool runs, and all files go to a scratch folder. Run: python scripts/route_check.py"""
import json
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
TOOL_LIMIT = 800
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
    ("watch binary search", "local:play_media"),
    ("what can you do", "local:capabilities"),
    ("what are your features", "local:capabilities"),
    ("help", "local:capabilities"),
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
    ("be chattier", "local:proactive_level"),
    ("be chatier", "local:proactive_level"),
    ("don't be chatty", "local:proactive_level"),
    ("be quiet", "local:proactive_level"),
    ("talk less", "local:proactive_level"),
    ("stop talking for two hours", "local:proactive_quiet"),
    ("stop talking for an hour", "local:proactive_quiet"),
    ("listen in Kannada", "local:set_language"),
    ("listen in hindu", "local:set_language"),
    ("use the jarvis voice", "local:change_voice"),
    ("use the female voice", "local:change_voice"),
    ("what voices do you have", "local:list_voices"),
    ("play the next one", "local"),
    # phrases from the live log: these used to cost 1100 to 1650 tokens
    ("Yeah okay, this is good", "chat"),
    ("This one", "chat"),
    ("a web interface like WhatsApp and Instagram", "tool:build_project"),
    ("what are your new features", "local:capabilities"),
    ("your features", "local:capabilities"),
    ("what's new", "local:capabilities"),
    ("can you build apps", "local:capabilities"),
    ("can you code", "local:capabilities"),
    ("can you browse the web", "local:capabilities"),
    ("update your notes with the lab report is due friday", "local:append_to_note"),
    ("add to notes: buy a cable", "local:append_to_note"),
    ("build something cool", "local:build_project"),
    # sentences from the live log
    ("So what are your new features?", "local:capabilities"),
    ("So can you now do it?", "local:capabilities"),
    ("So in your notes, can you update the features which you have?", "local:append_to_note"),
    ("So build your one and do it", "local:build_project"),
    ("open Google Chrome and search Jarvis capabilities and features", "local:browse_search"),
    ("Anyone which you can open like open GitHub and search Jarvis", "local:browse_search"),
]
# what the log session had just done, so a short follow-up must not drag the old tools along
BEFORE = ("draft an email to my professor about the deadline", "draft_text")
LONG_LINE = "Dear Professor, I am writing about the project deadline and would like a short extension. " * 2

calls = []


def fake_route(messages, max_tokens=500, want_json=True, local=False):
    calls.append({"messages": messages, "json": want_json})
    return ('{"action": "chat", "say": "ok"}' if want_json else "ok"), "mock"


done = []


def classify(text):
    del calls[:]
    del done[:]
    main.PENDING.clear()
    brain.RECENT[:] = [BEFORE[0]]
    brain.LAST_ACTION[0] = BEFORE[1]
    history = [{"role": "user", "content": BEFORE[0]},
               {"role": "assistant", "content": json.dumps({"action": "draft_text", "say": LONG_LINE})}] * 3
    if text in ("yes", "no"):
        main.PENDING.update({"action": "battery", "args": {}, "until": time.time() + 60})
    with mock.patch.object(brain, "route", fake_route), \
            mock.patch.object(brain.memory, "context", return_value=""), \
            mock.patch.object(main, "do_tool", lambda a, args, spoken="": done.append(a)), \
            mock.patch.object(main, "run_tool", lambda a, args, spoken: done.append(a)), \
            mock.patch.object(main.voice, "say", lambda *a, **k: None), \
            mock.patch.object(main.reminders, "active", return_value=None), \
            mock.patch.object(main.apps, "find_app", return_value="app"), \
            mock.patch.object(main.brain, "_history", history):
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

# the picker offers remember only when the sentence says remember, note or save
for text, want in (("find my resume file", False), ("where did I save my thesis", True), ("what hackathons are happening this month", False),
                   ("remember that my locker is 42", True), ("draft an email to my professor about the deadline", False)):
    names = classify(text)[1]
    ok = ("remember" in names) == want
    print(("ok   " if ok else "FAIL ") + f"remember {'offered' if want else 'not offered'} for {text!r}")
    if not ok:
        bad.append((text, "remember", names, 0))

import tempfile as _t  # noqa: E402
from jarvis.actions import capabilities as _cap, coder as _coder  # noqa: E402

can = {q: _cap.answer_can(q) for q in ("can you build apps", "can you code", "can you run code", "can you browse the web")}
for q, a in can.items():
    ok = a.startswith("Yes") and "can't" not in a.lower() and "cannot" not in a.lower()
    print(("ok   " if ok else "FAIL ") + f"{q!r} is answered from the registry: {a[:60]}")
    if not ok:
        bad.append((q, "yes", a, 0))
ok = "build project" in can["can you code"] and "run project" in can["can you run code"] and "browse open" in can["can you browse the web"]
print(("ok   " if ok else "FAIL ") + "the answers name real tools")
if not ok:
    bad.append(("tools", "named", can, 0))
vague = ["build something cool", "build me an app", "make a flask app", "create a project", "write me some code", "build something", "make a website please"]
specific = ["build me a todo app in python", "make a flask app that shows the time", "write a python script that renames my files", "create a calculator"]
ok = all(_coder.is_vague(v) for v in vague) and not any(_coder.is_vague(v) for v in specific)
print(("ok   " if ok else "FAIL ") + "vague build requests are told apart from real ones")
if not ok:
    bad.append(("vague", "", [v for v in vague if not _coder.is_vague(v)] + [v for v in specific if _coder.is_vague(v)], 0))
try:
    _coder.build_project({"request": "build something cool"})
    ok = False
except Exception as e:
    ok = "What should it do" in str(e) and _coder.asking()
print(("ok   " if ok else "FAIL ") + "a vague build asks one question and starts no plan")
if not ok:
    bad.append(("ask", "", "", 0))
ok = _coder.take_spec("a python script that renames my files") == "a python script that renames my files" and _coder.take_spec("another one") is None
print(("ok   " if ok else "FAIL ") + "the next sentence becomes the spec")
if not ok:
    bad.append(("spec", "", "", 0))

# the log sentences in detail: arguments, answers and nothing started that should not be
captured = []
LOG = {
    "So in your notes, can you update the features which you have?": ("append_to_note", {"topic": "jarvis features"}),
    "open Google Chrome and search Jarvis capabilities and features": ("browse_search", {"query": "Jarvis capabilities and features", "site": ""}),
    "Anyone which you can open like open GitHub and search Jarvis": ("browse_search", {"query": "Jarvis", "site": "github"}),
}
for text, (action, want_args) in LOG.items():
    del captured[:]
    with mock.patch.object(main, "run_tool", lambda a, args, sp: captured.append((a, args))), mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")), \
            mock.patch.object(main.brain, "chat", side_effect=AssertionError("brain")), mock.patch.object(main.browser, "ready", lambda: True):
        main._handle(text)
    got = captured[0] if captured else (None, {})
    ok = got[0] == action and all(got[1].get(k) == v for k, v in want_args.items()) and got[0] != "remember"
    print(("ok   " if ok else "FAIL ") + f"{text[:50]!r} -> {got[0]} {got[1] if len(str(got[1])) < 60 else ''}")
    if not ok:
        bad.append((text, action, got, 0))
ok = len(captured) == 1
print(("ok   " if ok else "FAIL ") + "and only one action runs for the last sentence")
if not ok:
    bad.append(("one action", "", captured, 0))

with mock.patch.object(main, "run_tool", lambda a, args, sp: captured.append((a, args))), mock.patch.object(main.browser, "ready", lambda: False):
    del captured[:]
    main._handle("open Google Chrome and search Jarvis capabilities and features")
ok = captured and captured[0][0] == "web_search" and "Jarvis capabilities" in captured[0][1]["query"]
print(("ok   " if ok else "FAIL ") + "without Playwright the same sentence falls back to a web search")
if not ok:
    bad.append(("fallback", "", captured, 0))
from jarvis.actions import browser as _browser  # noqa: E402
ok = (_browser.search_url("Jarvis capabilities and features", "").startswith("https://duckduckgo.com/?q=Jarvis%20capabilities")
      and _browser.search_url("Jarvis", "github") == "https://github.com/search?q=Jarvis")
print(("ok   " if ok else "FAIL ") + "the default search address is DuckDuckGo and GitHub opens its own search")
if not ok:
    bad.append(("urls", "", "", 0))
seen = []
with mock.patch.object(_browser.W, "run", lambda fn, timeout=60: seen.append(1) or True):
    try:
        out = tools.TOOLS["browse_search"]["fn"]({"query": "Jarvis", "site": "github"})
        ok = "Github" in out and "Jarvis" in out
    except Exception as e:
        ok = False
        out = repr(e)
print(("ok   " if ok else "FAIL ") + f"opening GitHub and searching does not crash: {out}")
if not ok:
    bad.append(("github", "", out, 0))

for q in ("So can you now do it?", "So can you now do it", "can you do it"):
    a = _cap.answer_can(q)
    ok = _cap.CAN.match(q) is not None and a.startswith("Yes") and "can't" not in a.lower() and "cannot" not in a.lower() and "not able" not in a.lower()
    print(("ok   " if ok else "FAIL ") + f"{q!r} never says it cannot run code: {a[:50]}")
    if not ok:
        bad.append((q, "yes", a, 0))
with mock.patch.object(_coder.brain, "code", side_effect=AssertionError("plan loop started")):
    try:
        _coder.build_project({"request": "build your one and do it"})
        ok = False
    except AssertionError:
        ok = False
    except Exception as e:
        ok = "What should it do" in str(e)
print(("ok   " if ok else "FAIL ") + "'build your one and do it' asks what to build and starts no plan")
if not ok:
    bad.append(("build your one", "", "", 0))
print(f"\npass rate: {len(CASES) - len(bad)}/{len(CASES)} ({100 * (len(CASES) - len(bad)) // len(CASES)}%)")
print(f"largest chat request ~{worst['chat']} tokens (system prompt ~{worst['system']}), largest tool request ~{worst['tool']}")
for text, want, got, tokens in bad:
    print(f"misroute: {text!r} wanted {want}, got {got} (~{tokens} tokens)")
sys.exit(1 if bad else 0)
