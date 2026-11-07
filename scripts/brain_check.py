"""Checks provider fallbacks with mocked HTTP. Run: python scripts/brain_check.py"""
import sys
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.brain import brain  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name)


calls = []


def groq(messages, use_json=True, model=None, max_tokens=300):
    calls.append((use_json, messages))
    return (None, 400) if len(calls) == 1 else ("{}", 200)


msgs = [{"role": "user", "content": "x"}]
with mock.patch.object(brain, "_groq", side_effect=groq):
    text, code = brain._try_groq(msgs, 100, True)
check("a 400 in JSON mode is retried once, plain, with the same messages",
      text == "{}" and len(calls) == 2 and calls[1] == (False, msgs))
del calls[:]
with mock.patch.object(brain, "_groq", side_effect=lambda *a, **k: (None, 400)) as g:
    brain._try_groq(msgs, 100, False)
check("a 400 on the plain path is not repeated", g.call_count == 1)

brain._spent.clear()
big = [{"role": "user", "content": "x" * 40000}]
order = []
providers = (("groq", lambda m, t, j: order.append("groq") or ("hi", 200)),
             ("openrouter", lambda m, t, j: order.append("openrouter") or ("hi", 200)))
with mock.patch.object(brain, "PROVIDERS", providers):
    brain.route(big, want_json=False)
check("a request over the minute budget goes to the next provider", order == ["openrouter"])
brain._spent.clear()
brain._spent["groq"] = brain.deque([(brain.time.time(), brain.TPM["groq"] - 50)])
with mock.patch.object(brain, "PROVIDERS", providers):
    order.clear()
    brain.route(msgs, max_tokens=100, want_json=False)
check("tokens already spent this minute count against the budget", order == ["openrouter"])
check("an image is counted as a fixed size, not its bytes",
      brain.estimate([{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "x" * 100000}}]}]) < 1000)

brain._busy.clear()
brain._spent.clear()
order = []
providers = (("groq", lambda m, t, j: order.append("groq") or (None, 429)),
             ("openrouter", lambda m, t, j: order.append("openrouter") or ("hello", 200)),
             ("ollama", lambda m, t, j: order.append("ollama") or (None, 0)))
with mock.patch.object(brain, "PROVIDERS", providers):
    text, name = brain.route([{"role": "user", "content": "x"}], want_json=False)
check("429 moves to the next provider", name == "openrouter" and order == ["groq", "openrouter"])
check("busy provider is skipped next time", "groq" in brain._busy)

brain._busy.clear()
with mock.patch.object(brain.config, "get", side_effect=lambda n, d="": {"CODE_MODEL": "x/y"}.get(n, d)), \
        mock.patch.object(brain, "_try_openrouter", return_value=(None, 429)), \
        mock.patch.object(brain, "route", return_value=("fallback", "groq")):
    out = brain.code("write code")
check("code model rate limit falls back to the chain", out == "fallback" and "code" in brain._busy)
print("failures:", results.count(False))
sys.exit(1 if False in results else 0)
