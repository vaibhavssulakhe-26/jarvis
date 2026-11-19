"""Local-first brain with fake providers: the local model answers by default, the cloud ("advanced") only for the user's words and heavy work,
with a daily count, a question before the last ten calls, honest fallbacks and nothing noisy sent out. No network. Run: python scripts/local_first_check.py"""
import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

tmp = tempfile.mkdtemp(prefix="jarvis-local-first-")
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
os.environ["GROQ_API_KEY"] = "gsk-fake"
os.environ["OPENROUTER_API_KEY"] = "or-fake"
os.environ.pop("BRAIN", None)
os.environ.pop("BRAIN_MODE", None)
os.environ["ADVANCED_DAILY"] = "40"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import events, stats  # noqa: E402
from jarvis.brain import advanced, agent, brain  # noqa: E402
from jarvis.core import config, main  # noqa: E402
from jarvis.core.errors import Ask  # noqa: E402
from jarvis import doctor  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:240] if detail and not ok else ""))
    if not ok:
        bad.append(name)


sent = {"ollama": [], "groq": [], "openrouter": []}
cloud_up = {"groq": True}


def fake_ollama(messages, max_tokens, want_json):
    sent["ollama"].append(messages)
    brain._record("ollama", True)
    return ("local answer" if not want_json else '{"say": "local json", "calls": []}'), 200


def fake_groq(messages, max_tokens, want_json):
    if not config.get("GROQ_API_KEY"):
        return None, 0
    sent["groq"].append(messages)
    if not cloud_up["groq"]:
        brain._record("groq", False, 500)
        return None, 500
    brain._record("groq", True)
    return "advanced answer", 200


def direct_groq(messages, use_json=True, model=None, max_tokens=300, effort="low"):
    return fake_groq(messages, max_tokens, use_json)


def stream_groq(messages, model, max_tokens, on_delta, effort="low"):
    text, code = fake_groq(messages, max_tokens, False)
    if text:
        on_delta(text)
    return text, code


def fake_openrouter(messages, max_tokens, want_json, models=None):
    sent["openrouter"].append(messages)
    return None, 0


def reset():
    for v in sent.values():
        v.clear()
    cloud_up["groq"] = True
    brain._busy.clear()
    brain._offline_until[0] = 0.0
    brain._outage.update(said=False, no_brain=False)
    brain.FAILED.clear()
    brain.HEALTH.clear()
    main.PENDING.clear()
    brain.begin_turn("")


def usage_file(calls):
    path = Path(tmp) / "usage.json"
    path.write_text(json.dumps({datetime.now().strftime("%Y-%m-%d"): {"advanced": {"calls": calls, "tokens": calls * 100}}}), encoding="utf-8")


def calls_today():
    return advanced.used()


tiers, said = [], []
events.listeners.append(lambda k, v: tiers.append(v) if k == "tier" else None)
providers = (("groq", fake_groq), ("openrouter", fake_openrouter), ("ollama", fake_ollama))
patches = [mock.patch.object(brain, "PROVIDERS", providers), mock.patch.object(brain, "_ensure_ollama", lambda: True),
           mock.patch.object(brain, "_groq_stream", stream_groq), mock.patch.object(brain, "_groq", direct_groq),
           mock.patch.object(brain, "_groq_tools", lambda *a, **k: (None, 0)),
           mock.patch.object(voice, "say", lambda t, *a, **k: said.append(str(t))),
           mock.patch.object(brain, "_try_openrouter", fake_openrouter)]
for p in patches:
    p.start()

try:
    # the default and the settings
    check("local first is the default mode", config.brain_mode() == "local_first")
    with mock.patch.dict(os.environ, {"BRAIN_MODE": "hybrid"}):
        check("BRAIN_MODE=hybrid is still available", config.brain_mode() == "hybrid")
    with mock.patch.dict(os.environ, {"BRAIN": "offline"}):
        check("the older BRAIN=offline still means offline", config.brain_mode() == "offline" and config.offline())

    # chat and simple questions stay local
    reset()
    tiers.clear()
    plan = brain.chat("how tall is mount everest")
    check("a simple question is answered by the local model", plan["say"] == "local answer" and len(sent["ollama"]) == 1)
    check("nothing went to the cloud", not sent["groq"] and not sent["openrouter"])
    check("the reply is not marked advanced", "advanced" not in tiers and tiers[-1] == "local model", tiers)
    check("no advanced call was counted", calls_today() == 0)
    reset()
    brain.ask("what is a stack")
    check("a plain ask stays local", len(sent["ollama"]) == 1 and not sent["groq"])
    check("local=True never reaches the cloud even when advanced", (reset(), brain.ask("x", local=True, advanced=True), not sent["groq"])[2])

    # the user's words
    for phrase in ("use advanced and tell me about tides", "think hard about why the sky is blue", "go deep on black holes"):
        reset()
        brain.begin_turn(phrase)
        tiers.clear()
        plan = brain.chat(phrase)
        check(f"'{phrase.split(' and')[0]}' goes to the cloud", plan["say"] == "advanced answer" and len(sent["groq"]) == 1 and not sent["ollama"], plan)
    check("and the reply carries the ADVANCED tier", tiers[-1] == "advanced", tiers)
    check("and one call is counted for the day", calls_today() == 1 or calls_today() >= 1)
    check("the next turn without the words is local again", (reset(), brain.begin_turn("what time is it in tokyo"), brain.chat("what time is it in tokyo"), not sent["groq"] and len(sent["ollama"]) == 1)[3])

    # heavy work
    reset()
    out = brain.ask("Summarise this", 200, advanced=True)
    check("advanced=True (a long document, research) uses the cloud", out == "advanced answer" and len(sent["groq"]) == 1)
    reset()
    with mock.patch.object(brain, "_code_cloud", lambda m, t, cloud_only=False: "cube(10);" if cloud_only else None):
        out = brain.code("write an openscad cube")
    check("code goes to the cloud and is counted", out == "cube(10);" and calls_today() >= 1)
    reset()
    plan = brain.chat("debug this traceback for me")
    check("a debugging chat is heavy and uses the cloud", plan["say"] == "advanced answer" and not sent["ollama"])
    reset()
    brain.chat("write me a python script that renames files")
    check("a code request in chat is heavy", len(sent["groq"]) == 1)

    # the cloud sees only what it needs
    reset()
    brain.begin_turn("use advanced explain recursion")
    history = [{"role": "user", "content": f"old question {i}"} for i in range(6)]
    history.insert(2, {"role": "assistant", "content": "No brain answered: the offline model is not available either."})
    big = [{"role": "system", "content": "persona"}] + history + [{"role": "user", "content": "use advanced explain recursion"}]
    brain.route(big, 100, want_json=False)
    got = sent["groq"][0]
    check("the cloud gets at most two earlier turns", len(got) <= 1 + 2 * advanced.CLOUD_TURNS + 1, len(got))
    check("a failure line is never sent along", not any("No brain answered" in str(m["content"]) for m in got))
    check("the request itself is last", got[-1]["content"] == "use advanced explain recursion")
    reset()
    brain.begin_turn("use advanced explain recursion")
    with mock.patch.object(brain.memory, "context", return_value="PRIVATE NOTE about the user"), mock.patch.object(brain.facts, "context", return_value="PRIVATE FACT"):
        brain.chat("use advanced explain recursion")
    check("memory and facts stay on the laptop", sent["groq"] and not any("PRIVATE" in str(m["content"]) for m in sent["groq"][0]), sent["groq"])

    # noise and failures never reach the cloud
    for noise in ("thank you", "Thanks for watching", "[Music]", "   ", "No brain answered: nothing"):
        reset()
        brain.begin_turn("use advanced")
        brain.route([{"role": "system", "content": "s"}, {"role": "user", "content": noise}], 50, want_json=False, advanced=True)
        check(f"'{noise.strip()[:20]}' never reaches the cloud", not sent["groq"] and not sent["openrouter"])

    # budget: ask before spending, used up, fallback
    reset()
    usage_file(33)
    check("left() counts the day's calls", advanced.left() == 7)
    reset()
    usage_file(33)
    brain.begin_turn("use advanced explain tides")
    try:
        brain.chat("use advanced explain tides")
        asked = ""
    except Ask as e:
        asked = str(e)
    check("under ten left: it asks before spending", "7 advanced calls left" in asked and asked.endswith("Say yes or no."), asked)
    check("and nothing was sent yet", not sent["groq"] and not sent["ollama"])
    check("and the question waits for a yes", main.PENDING.get("action") == "advanced_confirm" and main.PENDING["args"]["text"] == "use advanced explain tides")
    seen = []
    with mock.patch.object(main, "_handle", lambda text, via_wake=True: seen.append((text, advanced._t()["approved"]))):
        main.check_pending("yes please")
    check("a yes runs the request again with approval", seen == [("use advanced explain tides", True)], seen)
    reset()
    usage_file(33)
    brain.begin_turn("use advanced explain tides")
    try:
        brain.chat("use advanced explain tides")
    except Ask:
        pass
    said.clear()
    main.check_pending("no")
    check("a no cancels without spending", main.PENDING == {} and not sent["groq"] and "cancelled" in said[-1], said)
    reset()
    usage_file(33)
    advanced.replay("use advanced explain tides")
    plan = brain.chat("use advanced explain tides")
    check("an approved request goes through", plan["say"] == "advanced answer")
    reset()
    usage_file(40)
    brain.begin_turn("use advanced explain tides")
    said.clear()
    plan = brain.chat("use advanced explain tides")
    check("used up: the local model answers", plan["say"] == "local answer" and not sent["groq"])
    check("with one honest sentence", len(said) == 1 and "used up for today" in said[0] and "local model" in said[0], said)
    reset()
    usage_file(35)
    with mock.patch.dict(os.environ, {}), mock.patch.object(main.REMOTE, "gate", object(), create=True):
        brain.begin_turn("use advanced explain tides")
        plan = brain.chat("use advanced explain tides")
    check("a command from the phone is never asked, it stays local", plan["say"] == "local answer" and not sent["groq"])
    reset()
    usage_file(35)
    advanced.end()
    out = brain.ask("long summary", 100, advanced=True)
    check("background work under ten left does not ask and stays local", out == "local answer" and not main.PENDING)
    reset()
    brain.begin_turn("use advanced explain tides")
    other = []
    import threading
    t = threading.Thread(target=lambda: other.append(brain.ask("summarise the chat", 50)))
    t.start()
    t.join()
    check("the user's advanced words do not leak into another thread", other == ["local answer"] and not sent["groq"], other)
    brain.end_turn()
    check("and they end with the turn", not advanced.forced())
    usage_file(0)

    # cloud failure falls back honestly
    reset()
    cloud_up["groq"] = False
    brain.begin_turn("use advanced explain tides")
    said.clear()
    plan = brain.chat("use advanced explain tides")
    check("a cloud failure falls back to the local model", plan["say"] == "local answer")
    check("with one sentence naming the cause", len(said) == 1 and "Advanced did not answer" in said[0] and "local model" in said[0] and "500" in said[0], said)
    check("a failed call is not counted as advanced", calls_today() == 0)
    reset()
    with mock.patch.dict(os.environ, {"GROQ_API_KEY": "", "OPENROUTER_API_KEY": ""}):
        brain.begin_turn("use advanced explain tides")
        said.clear()
        brain.chat("use advanced explain tides")
    check("with no cloud key it says it is not set up", said and "not set up" in said[0], said)

    # tool plans
    reset()
    out = brain.tool_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "open the browser"}], [{"function": {"name": "open_app", "description": "x"}}])
    check("a tool plan is made by the local model", out and out["provider"] == "ollama" and not sent["groq"])
    check("the multi-step words are detected", advanced.is_multi_step("open the site and then search for pens") and not advanced.is_multi_step("open the site"))
    reset()
    with mock.patch.object(brain, "_groq_tools", lambda m, s, t: ({"content": "", "tool_calls": [{"id": "c0", "function": {"name": "open_app", "arguments": "{}"}}]}, 200)):
        out = brain.tool_turn([{"role": "system", "content": "s"}, {"role": "user", "content": "open it and then search for pens"}], [{"function": {"name": "open_app", "description": "x"}}], advanced=True)
    check("a multi-step plan uses the cloud and is counted", out and out["provider"] == "groq" and calls_today() == 1)

    # one model, five minutes, small context, no parallel requests
    reset()
    posts = []

    class Resp:
        status_code = 200

        def json(self):
            return {"message": {"content": "hi"}, "models": []}

    def fake_post(url, json=None, timeout=0):
        posts.append((url, json))
        return Resp()

    with mock.patch.object(brain._http, "post", fake_post), mock.patch.object(brain, "_free_gb", lambda: 3.0), \
            mock.patch.object(brain, "_ollama_model", lambda: "llama3.2:1b"), mock.patch.object(brain, "_loaded", lambda: {"phi4-mini:latest": 1}):
        text, code = brain._try_ollama([{"role": "user", "content": "hi"}], 50, False)
    chat_body = next(j for u, j in posts if u.endswith("/api/chat"))
    check("the local model is kept for five minutes", chat_body["keep_alive"] == "5m")
    check("a 1B model gets a 2048 context", chat_body["options"]["num_ctx"] == 2048 and brain._num_ctx("llama3.2:3b", 6.0) == 4096 and brain._num_ctx("llama3.2:3b", 2.0) == 2048)
    check("another loaded model is told to leave", any(u.endswith("/api/generate") and j["model"] == "phi4-mini:latest" and j["keep_alive"] == 0 for u, j in posts))
    check("requests to Ollama take a lock, so none run in parallel", hasattr(brain._ollama_lock, "acquire"))
    with mock.patch.object(brain, "_free_gb", lambda: 0.9), mock.patch.object(brain, "_loaded", lambda: {}):
        text, code = brain._try_ollama([{"role": "user", "content": "hi"}], 50, False)
    check("too little memory skips the local model with a stated cause", text is None and "too little free memory" in brain.why_down("ollama"), brain.why_down("ollama"))

    # no brain at all
    reset()
    with mock.patch.object(brain, "_try_ollama", lambda m, t, j: (None, -1)), mock.patch.object(brain, "PROVIDERS", (("groq", fake_groq), ("openrouter", fake_openrouter), ("ollama", lambda m, t, j: (None, -1)))):
        brain.begin_turn("hello there")
        plan = brain.chat("hello there")
        line = brain.outage_line()
    check("a local failure does not silently call the cloud", plan is None and not sent["groq"])
    check("the no-brain line points to 'use advanced'", "use advanced" in line, line)

    # numbers: tokens per provider per day, calls on Stats
    reset()
    usage_file(0)
    brain.begin_turn("use advanced explain tides")
    brain.chat("use advanced explain tides")
    brain.begin_turn("hello again my friend")
    brain.chat("hello again my friend")
    week, today = stats.usage()
    check("tokens are counted per provider and day", sum(r["tokens"] for k, r in today.items() if k.startswith("groq")) > 0 and today.get("ollama", {}).get("tokens", 0) > 0, today)
    check("advanced calls are not double counted in the provider totals", "advanced" not in today and "advanced" not in week)
    used, cap, tokens = stats.advanced_today()
    check("Stats shows advanced calls used and the daily cap", used == 1 and cap == 40 and tokens > 0, (used, cap, tokens))
    check("the stats text has an advanced line", "Advanced (cloud) today: 1 of 40" in stats.build()[1], stats.build()[1])

    # doctor
    names = {r["name"]: r for r in doctor.run(level=lambda: 0.02, skip_mic=True)}
    check("doctor reports the advanced tier", "advanced (cloud)" in names and "calls used today" in names["advanced (cloud)"]["detail"], names.get("advanced (cloud)"))
    check("doctor reports the local model with free memory", "ollama" in names and "GB free" in names["ollama"]["detail"] or names["ollama"]["status"] == "warn", names.get("ollama"))
    check("model by free memory: 1B under 2.5 GB, 3B above", brain.pick_ollama_model(["llama3.2:1b", "llama3.2:3b"], 2.4) == "llama3.2:1b" and brain.pick_ollama_model(["llama3.2:1b", "llama3.2:3b"], 2.6) == "llama3.2:3b")

    brain.note_models([{"name": "phi4-mini:latest", "size": 2491876774, "details": {"parameter_size": "3.8B"}},
                       {"name": "llama3.2:1b", "size": 1321098329, "details": {"parameter_size": "1.2B"}},
                       {"name": "nomic-embed-text:latest", "size": 274000000, "details": {"parameter_size": "137M"}}])
    check("a model whose name has no size is judged by the size Ollama reports",
          brain.pick_ollama_model(["phi4-mini:latest", "llama3.2:1b"], 1.9) == "llama3.2:1b" and brain._billions("nomic-embed-text:latest") < 1)
    brain._params.clear()

    # the agent hands a heavy plan up
    check("the agent keeps only two turns of history for an advanced plan", "history(text, 2 if heavy" in Path(agent.__file__).read_text(encoding="utf-8"))
finally:
    for p in patches:
        p.stop()

print("failures:", len(bad))
sys.exit(1 if bad else 0)
