"""Provider status comes from the last real call: a failing provider is named, one failure message per turn, a working provider is used when only one
fails, and Stats shows today's tokens per provider. No network. Run: python scripts/provider_check.py"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

tmp = tempfile.mkdtemp(prefix="jarvis-provider-")
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
os.environ["GROQ_API_KEY"] = "gsk-fake"
os.environ["OPENROUTER_API_KEY"] = "or-fake"
os.environ.pop("BRAIN", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["BRAIN_MODE"] = "hybrid"
import requests  # noqa: E402

from jarvis.actions import stats  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:240] if detail and not ok else ""))
    if not ok:
        bad.append(name)


def reply(code, content="ok"):
    r = requests.Response()
    r.status_code = code
    r._content = json.dumps({"choices": [{"message": {"content": content}}]} if code < 400 else {"error": {"message": "nope"}}).encode()
    return r


posts = []


def fake_post(url, **kw):
    posts.append("groq" if "groq" in url else "openrouter")
    return responses[posts[-1]]()


responses = {}
said = []
msgs = [{"role": "user", "content": "hello there"}]
patches = [mock.patch.object(brain._http, "post", fake_post), mock.patch.object(brain, "_ensure_ollama", lambda: False),
           mock.patch.object(brain, "_room", lambda n, t: True), mock.patch.object(brain, "log_usage"),
           mock.patch.object(voice, "say", lambda t, *a, **k: said.append(str(t)))]
for p in patches:
    p.start()


def reset():
    brain.HEALTH.clear()
    brain.FAILED.clear()
    brain._busy.clear()
    brain._offline_until[0] = 0.0
    brain._outage.update(said=False, no_brain=False)
    del posts[:], said[:]
    brain.begin_turn()


# nothing asked yet: the panel must not claim anything
reset()
st = brain.provider_status()
check("before any call nothing is called reachable", "reachable" not in st["groq"] and "not called yet" in st["groq"], st["groq"])

# Groq works, then fails: the status follows the last real call
responses.update(groq=lambda: reply(200, "fine"), openrouter=lambda: reply(200, "fine"))
text, who = brain.route(msgs, 50, want_json=False)
check("a working call is reported as worked", who == "groq" and brain.provider_state("groq")[0] == "ok" and "worked" in brain.provider_status()["groq"], str(brain.provider_status()))
responses["groq"] = lambda: reply(500)
text, who = brain.route(msgs, 50, want_json=False)
st = brain.provider_status()
check("when Groq fails, OpenRouter answers", who == "openrouter" and text == "fine", str((who, text)))
check("the failing provider is named with its code, the working one is not blamed", "failed" in st["groq"] and "500" in st["groq"] and "worked" in st["openrouter"], str(st))
check("a single failure says nothing aloud", not said, str(said))
responses["groq"] = lambda: reply(200, "back")
brain.route(msgs, 50, want_json=False)
check("the next good call clears the failure", brain.provider_state("groq")[0] == "ok", str(brain.provider_status()))

# an unreadable 200 is a failure, not "reachable"
reset()
responses["groq"] = lambda: (lambda r: (setattr(r, "_content", b"not json"), r)[1])(reply(200))
brain.route(msgs, 50, want_json=False)
check("an unreadable reply counts as failed", brain.provider_state("groq")[0] == "bad" and "could not read" in brain.provider_status()["groq"], str(brain.provider_status()))

# both clouds fail and no offline model: one message for the whole turn, naming both
reset()
responses.update(groq=lambda: reply(500), openrouter=lambda: reply(401))
got, who = brain.route(msgs, 50, want_json=False)
line = brain.outage_line()
voice.say(line)
check("nothing answered", got is None)
check("one failure message in the turn, not two", len([s for s in said if s]) == 1 and said[0] == line, str(said))
check("it names the provider that failed and why", "Groq" in line and "500" in line and "OpenRouter" in line and "key" in line, line)
check("a second ask in the same turn adds no second message", brain.outage_line() == "", brain.outage_line())
brain.begin_turn()
check("the next turn gets a shorter line", len(brain.outage_line()) < len(line))

# the offline model answering says the failure once, with the answer
reset()
responses.update(groq=lambda: reply(500), openrouter=lambda: reply(500))
with mock.patch.object(brain, "PROVIDERS", (brain.PROVIDERS[0], brain.PROVIDERS[1], ("ollama", lambda m, t, j: (brain._record("ollama", True) or "local", 200)))):
    got, who = brain.route(msgs, 50, want_json=False)
check("the offline model answers when both clouds fail", who == "ollama", str((who, got)))
check("exactly one message, naming Groq", len(said) == 1 and "Groq" in said[0] and "OpenRouter" in said[0], str(said))

# a native tool call that fails on Groq is not repeated on Groq
reset()
responses.update(groq=lambda: reply(500), openrouter=lambda: reply(200, json.dumps({"say": "from openrouter", "calls": []})))
out = brain.tool_turn([{"role": "user", "content": "hi"}], [{"type": "function", "function": {"name": "x", "description": "x", "parameters": {}}}])
check("a failed Groq tool call moves to OpenRouter and does not ask Groq twice", out and out["provider"] == "openrouter" and posts.count("groq") == 1, f"{out} {posts}")
check("and that turn said nothing aloud", not said, str(said))

# the vision or large model failing does not mark the text model down
reset()
responses.update(groq=lambda: reply(200))
brain._record("groq-strong", False, 429)
check("a failing large model leaves the fast model's status alone", brain.provider_state("groq")[0] != "bad")

# tokens today per provider on Stats
day = datetime.now().strftime("%Y-%m-%d")
(Path(tmp) / "usage.json").write_text(json.dumps({"2001-01-01": {"groq": {"calls": 9, "tokens": 9000}},
                                                 day: {"groq": {"calls": 3, "tokens": 1200}, "openrouter": {"calls": 1, "tokens": 300}}}))
week, today = stats.usage()
spoken, full = stats.build()
check("Stats has today's tokens per provider", today["groq"]["tokens"] == 1200 and today["openrouter"]["tokens"] == 300, str(today))
check("an older day is not shown as today", "today 3 requests, 1200 tokens" in full and "today 0 requests, 0 tokens" in full, full)
(Path(tmp) / "usage.json").write_text(json.dumps({"2001-01-01": {"groq": {"calls": 9, "tokens": 9000}}}))
check("with nothing today the row is empty, not yesterday's", stats.usage()[1] == {})

for p in patches:
    p.stop()
print("\n" + ("all passed" if not bad else f"{len(bad)} failed"))
sys.exit(1 if bad else 0)
