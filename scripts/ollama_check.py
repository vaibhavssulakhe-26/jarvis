"""The local model: where Ollama is found, proxies ignored, every failure kind named exactly, the streaming timeout (the wait between chunks, not the whole
answer), the short chat prompt, the preload, the status text and `doctor --ollama`. Fake servers on a real local port; a real Ollama is used too when one is
running (skipped when it is not). Run: python scripts/ollama_check.py"""
import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-ollama-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
for name in ("OLLAMA_URL", "OLLAMA_HOST", "OLLAMA_MODEL", "BRAIN", "BRAIN_MODE", "HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY"):
    os.environ.pop(name, None)
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "scripts" / "fakes"))

import fake_ollama  # noqa: E402
import requests  # noqa: E402

from jarvis import doctor  # noqa: E402
from jarvis.actions import events  # noqa: E402
from jarvis.brain import brain, local  # noqa: E402
from jarvis.core import config  # noqa: E402
from jarvis.ui import status  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


log = []
events.listeners.append(lambda k, v: log.append((k, v)))
USER = [{"role": "user", "content": "can you hear me?"}]
mock.patch.object(brain, "_ensure_ollama", lambda: True).start()
mock.patch.object(brain, "_free_gb", lambda: 3.0).start()
mock.patch.object(brain, "_ollama_model", lambda: "llama3.2:1b").start()


def fresh(**cfg):
    brain.HEALTH.clear()
    brain.FAILED.clear()
    log.clear()
    local.LAST.clear()
    srv = fake_ollama.start(**cfg)
    local._use["url"] = srv.url
    return srv


def call(srv_cfg=None, messages=USER, max_tokens=200, want_json=False):
    return brain._try_ollama(messages, max_tokens, want_json)


def activity():
    return " | ".join(v for k, v in log if k == "sys")


saved = (local.FIRST_COLD, local.FIRST_WARM, local.GAP_SECONDS)

# ---- where Ollama is ----
check("OLLAMA_HOST style values are normalised", local.normalise("127.0.0.1:11434") == "http://127.0.0.1:11434" and local.normalise("0.0.0.0") == "http://127.0.0.1:11434"
      and local.normalise("localhost") == "http://localhost:11434" and local.normalise("http://box:9999/") == "http://box:9999" and local.normalise("") == "")
check("the default is localhost on 11434", local.configured_url() == "http://localhost:11434")
with mock.patch.dict(os.environ, {"OLLAMA_HOST": "0.0.0.0:11500"}):
    check("OLLAMA_HOST is used when OLLAMA_URL is not set", local.configured_url() == "http://127.0.0.1:11500")
    with mock.patch.dict(os.environ, {"OLLAMA_URL": "http://other:1234"}):
        check("OLLAMA_URL wins over OLLAMA_HOST", local.configured_url() == "http://other:1234")
check("localhost and 127.0.0.1 are each other's alternate", local.alternate("http://localhost:1") == "http://127.0.0.1:1" and local.alternate("http://127.0.0.1:1") == "http://localhost:1"
      and local.alternate("http://box:1") == "")

# ---- proxies are ignored ----
srv = fresh()
with mock.patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9", "http_proxy": "http://127.0.0.1:9"}):
    text, code = call()
srv.stop()
check("a dead proxy in the environment does not stop the local call", text == "Yes, I can hear you." and code == 200, f"{text!r} {code}")

# ---- the other spelling of this machine ----
srv = fresh()
port = srv.server_address[1]
local._use["url"] = f"http://localhost:{port}"
real_get = local.http.get


def refuse_localhost(url, **kw):
    if "localhost" in url:
        raise requests.ConnectionError("Connection refused")
    return real_get(url, **kw)


with mock.patch.object(local.http, "get", refuse_localhost):
    r = local.request("get", "/api/tags", timeout=3)
check("a refused localhost is retried on 127.0.0.1 and remembered", r.status_code == 200 and local._use["url"] == f"http://127.0.0.1:{port}", str(local._use))
srv.stop()

# ---- a good streamed answer, slow first word, fast after ----
local.FIRST_COLD, local.FIRST_WARM, local.GAP_SECONDS = 6, 1, 1
srv = fresh(first_delay=2.0)
started = time.time()
text, code = call()
took = time.time() - started
srv.stop()
check("a cold model with a slow first word still answers", text == "Yes, I can hear you." and code == 200 and 1.8 <= took < 5, f"{text!r} {took:.1f}")
check("the answer is recorded as working", brain.HEALTH["ollama"]["ok"] and local.LAST["ok"] and local.LAST["first_token"] >= 1.8 and local.LAST["warm"] is False)
srv = fresh(reply=[f"word{i} " for i in range(9)], gap=0.4, loaded=["llama3.2:1b"])
started = time.time()
text, code = call()
took = time.time() - started
srv.stop()
check("the timeout is the wait between chunks, not the whole answer", code == 200 and text.count("word") == 9 and took > local.FIRST_WARM + local.GAP_SECONDS, f"{took:.1f} s {text!r}")
deltas = []
srv = fresh()
body = {"model": "llama3.2:1b", "messages": USER, "stream": True}
text, meta = local.stream_chat(body, "llama3.2:1b", True, on_delta=deltas.append)
srv.stop()
check("chunks reach on_delta as they arrive", deltas == ["Yes, ", "I can ", "hear you."] and meta["prompt_eval_count"] == 42)

# ---- every failure kind, named exactly ----
local.FIRST_COLD = 1
cases = []
srv = fresh(first_delay=3.0)
started = time.time()
text, code = call()
took = time.time() - started
why = brain.why_down("ollama")
cases.append(("a cold first word that never comes", text is None and local.LAST["kind"] == "timeout" and "warming up" in why and "1 s" in why and took < 2.8 and code == local.CODES["timeout"], why))
a = activity()
cases.append(("it is logged with kind, exception, URL and model", "kind=timeout" in a and "exception=ReadTimeout" in a and srv.url in a and "model=llama3.2:1b" in a and "not loaded" in a, a))
cases.append(("a timeout never says could not be reached", "could not be reached" not in why and "could not be reached" not in brain.provider_state("ollama")[1], brain.provider_state("ollama")[1]))
srv.stop()

srv = fresh(first_delay=3.0, loaded=["llama3.2:1b"])
text, code = call()
why = brain.why_down("ollama")
cases.append(("a loaded model that is silent is a timeout, not warming up", local.LAST["kind"] == "timeout" and "warming up" not in why and "timed out after 1 s" in why and "was loaded" in activity(), why))
srv.stop()

srv = fresh(stall_after=1, stall_seconds=10)
started = time.time()
text, code = call()
took = time.time() - started
why = brain.why_down("ollama")
cases.append(("an answer that stops mid-way is a stall", text is None and local.LAST["kind"] == "stalled" and "mid-reply" in why and took < 4, f"{why} {took:.1f}"))
srv.stop()

srv = fresh(chat_status=404, chat_body="model 'llama3.2:1b' not found, try pulling it first")
text, code = call()
why = brain.why_down("ollama")
cases.append(("404 means the model is not installed, with the pull command", local.LAST["kind"] == "missing" and "ollama pull llama3.2:1b" in why and local.LAST["status"] == 404, why))
srv.stop()

srv = fresh(chat_status=500, chat_body="model requires more system memory (2.2 GiB) than is available (1.0 GiB)")
text, code = call()
why = brain.why_down("ollama")
cases.append(("a memory error from Ollama is out of memory", local.LAST["kind"] == "oom" and "ran out of memory" in why and "2.2 GiB" in why, why))
srv.stop()

srv = fresh(chat_error="llama runner process has terminated: cudaMalloc failed: out of memory; model requires more system memory")
text, code = call()
cases.append(("an out-of-memory error in the middle of the stream is caught", local.LAST["kind"] == "oom", brain.why_down("ollama")))
srv.stop()

srv = fresh(chat_status=500, chat_body="something broke inside")
text, code = call()
why = brain.why_down("ollama")
cases.append(("any other HTTP error says the status and the message", local.LAST["kind"] == "http" and "HTTP 500" in why and "something broke inside" in why, why))
srv.stop()

srv = fresh(reply=[])
text, code = call()
cases.append(("an empty reply is not treated as a working call", code == -2 and not brain.HEALTH["ollama"]["ok"], str(code)))
srv.stop()

brain.HEALTH.clear()
log.clear()
dead = f"http://127.0.0.1:{fake_ollama.closed_port()}"
local._use["url"] = dead
local.http.trust_env = False
with mock.patch.object(brain, "_ensure_ollama", lambda: True):
    text, code = call()
why = brain.why_down("ollama")
cases.append(("a closed port is refused, and only then is it called refused", local.LAST["kind"] == "refused" and "refused the connection" in why and dead in why and "ConnectionError" in activity(), why))

local._use["url"] = dead
with mock.patch.object(brain, "_ensure_ollama", lambda: False), mock.patch.object(brain.shutil, "which", lambda n: None):
    brain.HEALTH.clear()
    text, code = call()
cases.append(("no ollama command says it is not installed", "not installed" in brain.why_down("ollama") and local.LAST["kind"] == "refused", brain.why_down("ollama")))
with mock.patch.object(brain, "_ensure_ollama", lambda: False), mock.patch.object(brain.shutil, "which", lambda n: "/usr/bin/ollama"):
    brain.HEALTH.clear()
    text, code = call()
cases.append(("a server that will not start says so", "did not start" in brain.why_down("ollama"), brain.why_down("ollama")))

srv = fresh()
with mock.patch.object(brain, "_free_gb", lambda: 0.8):
    text, code = call()
why = brain.why_down("ollama")
posted_chat = [u for u, _ in srv.posts if u == "/api/chat"]
cases.append(("the RAM gate names the memory and never calls the model", local.LAST["kind"] == "ram" and "0.8 GB" in why and "1.5 GB" in why and not posted_chat and code == local.CODES["ram"], why))
a = activity()
cases.append(("the RAM gate is logged on the Activity page", "was skipped" in a and "kind=ram" in a, a))
srv.stop()
for name, ok, detail in cases:
    check(name, ok, str(detail))

# the Brains card and the self block read the real cause
srv = fresh(chat_status=404, chat_body="model not found")
call()
level, text = brain.provider_state("ollama")
check("the Brains card state carries the cause", level == "bad" and "ollama pull" in text and "could not be reached" not in text, text)
check("the self block carries it too", "ollama pull" in brain.self_block() or "not installed" in brain.self_block() or "does not have the model" in brain.self_block())
srv.stop()

# ---- the short chat prompt ----
config.PET_NAME = "Boss"
full = [{"role": "system", "content": f"You are {config.ASSISTANT}, a friendly voice companion and a good engineer on the user's Linux laptop. " + "Be accurate. " * 120 + "\nTool categories: a, b, c\nSELF BLOCK"}]
history = []
for i in range(10):
    history += [{"role": "user", "content": f"question {i} " + "x" * 400}, {"role": "assistant", "content": f"answer {i} " + "y" * 400}]
msgs = full + history + [{"role": "user", "content": "can you hear me?"}]
short = local.compact(msgs)
tokens = brain.estimate(short)
check("plain chat for the local model is about 400 tokens or less", tokens <= 400, str(tokens))
check("the persona is short", brain.estimate(short[:1]) <= 150, str(brain.estimate(short[:1])))
check("it has the nickname and the date", "Boss" in short[0]["content"] and str(time.localtime().tm_year) in short[0]["content"])
check("it has no tool list and no self block", "Tool categories" not in short[0]["content"] and "SELF BLOCK" not in short[0]["content"])
check("only the last four turns ride along, cut short", len(short) == 1 + 8 + 1 and all(len(m["content"]) <= local.HISTORY_CHARS for m in short[1:-1]) and short[-1]["content"] == "can you hear me?")
check("the oldest turns are the ones dropped", short[1]["content"].startswith("question 6") and short[-2]["content"].startswith("answer 9"))
plan = [{"role": "system", "content": "Reply with JSON. Tools: a, b"}, {"role": "user", "content": "open it"}]
check("a tool plan or any other prompt is left alone", local.compact(plan) == plan)
check("the answer length is capped near 200 for chat, drafts get more, plans keep theirs",
      local.predict_cap(450, False) == 200 and local.predict_cap(900, False) == 500 and local.predict_cap(500, True) == 500 and local.predict_cap(120, False) == 120)
srv = fresh()
brain._try_ollama(msgs, 450, False)
sent = next(b for u, b in srv.posts if u == "/api/chat")
check("the request sent is the short one with num_predict 200 and streaming", sent["options"]["num_predict"] == 200 and sent["stream"] is True and len(sent["messages"]) == 10)
srv.posts.clear()
brain._try_ollama(plan, 300, True)
sent = next(b for u, b in srv.posts if u == "/api/chat")
check("a JSON plan goes out unchanged with its own limit", sent["messages"] == plan and sent["options"]["num_predict"] == 300 and sent.get("format") == "json")
srv.stop()
config.PET_NAME = ""
req, _, limit = brain.chat_request("can you hear me?")
check("chat_request builds the same messages chat sends", req[0]["role"] == "system" and req[-1]["content"] == "can you hear me?" and limit > 0)

# ---- preload and the warming status ----
srv = fresh(generate_delay=1.5)
t = threading.Thread(target=lambda: brain.preload_local(), daemon=True)
t.start()
time.sleep(0.4)
warming_during = local.warming()
snap = status.snapshot(status.Tracker(), {"groq": "ok", "openrouter": "idle", "ollama": "idle"})
label = status.brain_label(snap)
state_text = brain.provider_state("ollama")[1]
t.join(5)
gen = [b for u, b in srv.posts if u == "/api/generate"]
check("the model is preloaded with a five minute keep-alive", gen and gen[0]["model"] == "llama3.2:1b" and gen[0]["keep_alive"] == "5m" and gen[0]["prompt"] == "", str(gen))
check("while it loads the state says warming up", warming_during and label == "local, warming up" and "warming up" in state_text, f"{warming_during} {label} {state_text}")
check("and it stops saying so afterwards", not local.warming() and "warm" in " ".join(v for k, v in log if k == "sys"))
srv.posts.clear()
with mock.patch.object(brain, "_free_gb", lambda: 1.0):
    ok = brain.preload_local()
check("no preload when free RAM is under the gate, and it says why", not ok and not srv.posts and "not preloaded" in activity() and "1.0 GB" in activity(), activity())
with mock.patch.dict(os.environ, {"BRAIN_MODE": "hybrid"}):
    ok = brain.preload_local()
check("no preload in hybrid mode (the cloud answers first)", not ok and not srv.posts)
srv.stop()

# ---- doctor --ollama ----
srv = fresh(first_delay=0.2)
lines, good = doctor.ollama_report()
joined = "\n".join(lines)
check("doctor --ollama makes the chat call and prints the result", good and "result       pass" in joined and "request      'can you hear me?'" in joined, joined[-300:])
check("it prints the URL, proxy, localhost spellings, model, memory and timeouts", all(w in joined for w in ("url ", "proxy ", "localhost", "127.0.0.1", "model ", "memory ", "timeouts")))
srv.stop()
srv = fresh(chat_status=404, chat_body="model not found")
lines, good = doctor.ollama_report()
joined = "\n".join(lines)
check("on a failure it prints the kind, exception, status, URL and model", not good and "FAIL" in joined and "kind=missing" in joined and "status=404" in joined and "model=llama3.2:1b" in joined, joined[-300:])
srv.stop()
with mock.patch.dict(os.environ, {"HTTPS_PROXY": "http://proxy.test:3128"}):
    check("doctor --ollama names the proxy variables it ignores", "HTTPS_PROXY" in local.proxy_variables())

# ---- a real Ollama, when there is one ----
local._use["url"] = None
local.FIRST_COLD, local.FIRST_WARM, local.GAP_SECONDS = saved
real = None
try:
    real = requests.get(local.configured_url() + "/api/tags", timeout=2, proxies={"http": None, "https": None}).json().get("models", [])
except (requests.RequestException, ValueError):
    pass
if not real:
    print("skip real Ollama: not running here")
else:
    names = [m["name"] for m in real]
    mock.patch.stopall()
    mock.patch.object(brain, "_ensure_ollama", lambda: True).start()
    brain._ollama_name.update(t=0.0, name=None)
    brain.HEALTH.clear()
    free = brain._free_gb()
    if free is not None and free < brain.MIN_FREE_GB and not brain._loaded():
        print(f"skip real Ollama: only {free:.1f} GB free, under the {brain.MIN_FREE_GB} GB gate")
    else:
        started = time.time()
        text, code = brain._try_ollama(USER, 100, False)
        check("a real Ollama answers 'can you hear me?' with the short prompt", bool(text) and code == 200, f"{local.LAST} {brain.why_down('ollama')}")
        if text:
            check("and the real call is recorded with its first-word time", local.LAST.get("ok") and local.LAST.get("first_token", 99) < local.FIRST_COLD, str(local.LAST))

sys.exit(1 if bad else 0)
