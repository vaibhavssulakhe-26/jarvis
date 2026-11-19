"""The local model (Ollama): where it is, one streaming call whose timeout is the wait between chunks, a short prompt for plain chat, the preload,
and an exact, named cause for every failure. Nothing here ever goes through a proxy."""
import json
import os
import queue
import socket
import threading
import time
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

import requests

from ..core import config, lang, profile

DEFAULT_URL = "http://localhost:11434"
CONNECT_SECONDS = 3
FIRST_COLD = int(config.get("OLLAMA_FIRST_COLD", "60") or 60)
FIRST_WARM = int(config.get("OLLAMA_FIRST_WARM", "15") or 15)
GAP_SECONDS = int(config.get("OLLAMA_GAP", "15") or 15)
KEEP_ALIVE = "5m"
CHAT_TOKENS = 200
DRAFT_TOKENS = 500
HISTORY_MESSAGES = 8
HISTORY_CHARS = 120
LOCAL_BUDGET = 400
MIN_FREE_GB = 1.5

# the code a failure kind leaves in brain.HEALTH
CODES = {"refused": -1, "empty": -2, "ram": -4, "timeout": -5, "stalled": -6, "missing": -7, "oom": -8, "dropped": -9, "http": -10, "not_installed": -11}

http = requests.Session()
http.trust_env = False
LAST = {}
state = {"warming": False, "since": 0.0, "model": ""}
_use = {"url": None}


class LocalError(Exception):
    """A failed call to the local model with its kind (refused, timeout, stalled, missing, oom, ram, http, dropped, empty), the exception type and everything needed to log it."""

    def __init__(self, kind, message, exc="", status=0, url="", model="", seconds=0.0, warm=None):
        super().__init__(message)
        self.kind, self.message, self.exc, self.status = kind, message, exc, status
        self.url, self.model, self.seconds, self.warm = url, model, seconds, warm

    @property
    def code(self):
        return CODES.get(self.kind, -1)

    def cause(self):
        """What to say to the user: the real reason, in words."""
        return self.message

    def line(self):
        """The one Activity line: kind, exception, message, URL, model and time."""
        bits = [f"kind={self.kind}"]
        if self.exc:
            bits.append(f"exception={self.exc}")
        if self.status:
            bits.append(f"status={self.status}")
        bits += [f"url={self.url}", f"model={self.model}", f"after={self.seconds:.1f}s"]
        if self.warm is not None:
            bits.append("model was " + ("loaded" if self.warm else "not loaded"))
        return "local model failed: " + self.message + " (" + ", ".join(b for b in bits if b) + ")"


# ---------- where Ollama is ----------
def normalise(raw):
    """http://host:port for whatever OLLAMA_URL or OLLAMA_HOST holds: a scheme is added, 0.0.0.0 means this machine, the port defaults to 11434."""
    raw = str(raw or "").strip()
    if not raw:
        return ""
    if "://" not in raw:
        raw = "http://" + raw
    parts = urlsplit(raw)
    host = parts.hostname or "localhost"
    if host in ("0.0.0.0", "::"):
        host = "127.0.0.1"
    port = parts.port or 11434
    host = f"[{host}]" if ":" in host else host
    return urlunsplit((parts.scheme or "http", f"{host}:{port}", "", "", ""))


def configured_url():
    return normalise(config.get("OLLAMA_URL") or os.environ.get("OLLAMA_HOST") or config.get("OLLAMA_HOST")) or DEFAULT_URL


def url():
    return _use["url"] or configured_url()


def alternate(base):
    """localhost and 127.0.0.1 are not always the same place (localhost can resolve to ::1 where Ollama does not listen)."""
    parts = urlsplit(base)
    swap = {"localhost": "127.0.0.1", "127.0.0.1": "localhost"}.get(parts.hostname or "")
    return urlunsplit((parts.scheme, f"{swap}:{parts.port or 11434}", "", "", "")) if swap else ""


def request(method, path, **kw):
    """One call to Ollama. A refused connection is retried once on the other spelling of this machine, and the spelling that works is remembered."""
    base = url()
    try:
        return getattr(http, method)(base + path, **kw)
    except requests.ConnectionError:
        other = alternate(base)
        if not other:
            raise
        r = getattr(http, method)(other + path, **kw)
        _use["url"] = other
        return r


def proxy_variables():
    return sorted(k for k in os.environ if k.upper() in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY") and os.environ[k])


# ---------- errors ----------
def _kind_from_text(status, body):
    text = (body or "").lower()
    if status == 404 or "not found" in text and "model" in text:
        return "missing"
    if "memory" in text and ("system" in text or "available" in text or "requires" in text):
        return "oom"
    return "http"


def from_http(status, body, model, seconds, warm):
    kind = _kind_from_text(status, body)
    base = url()
    snippet = " ".join(str(body or "").split())[:120]
    if kind == "missing":
        msg = f"does not have the model {model} installed (run: ollama pull {model})"
    elif kind == "oom":
        msg = f"ran out of memory loading {model}" + (f": {snippet}" if snippet else "")
    else:
        msg = f"answered HTTP {status}" + (f": {snippet}" if snippet else "")
    return LocalError(kind, msg, status=status, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)


def from_exception(exc, model, seconds, warm, first_wait=0, got_first=False):
    base = url()
    name = type(exc).__name__
    if isinstance(exc, requests.Timeout):
        return timeout_error(model, seconds, warm, got_first, exc=name)
    if isinstance(exc, requests.ConnectionError):
        text = str(exc).lower()
        if "refused" in text or "failed to establish" in text or "max retries" in text and not got_first:
            msg = f"refused the connection at {base} (is ollama serve running?)"
            return LocalError("refused", msg, exc=name, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)
        return LocalError("dropped", f"dropped the connection while answering ({name})", exc=name, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)
    return LocalError("http", f"failed with {name}: {str(exc)[:120]}", exc=name, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)


def timeout_error(model, seconds, warm, got_first, exc="ReadTimeout"):
    base = url()
    if got_first:
        return LocalError("stalled", f"stopped answering mid-reply (no word for {GAP_SECONDS} s)", exc=exc, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)
    if warm:
        msg = f"timed out after {seconds:.0f} s with no first word, although the model was loaded"
    else:
        msg = f"is still warming up: no first word after {seconds:.0f} s while loading {model}"
    return LocalError("timeout", msg, exc=exc, url=base + "/api/chat", model=model, seconds=seconds, warm=warm)


def skipped(free):
    return LocalError("ram", f"was skipped: {free:.1f} GB of memory free, it needs {MIN_FREE_GB} GB", url=url() + "/api/chat", model="", seconds=0.0)


def report(err):
    """Say the failure where it can be seen: the console and the Activity page, with every detail. Returns the error."""
    from ..actions import events
    turn = LAST.get("turn")
    LAST.clear()
    if turn:
        LAST["turn"] = turn
    LAST.update(ok=False, kind=err.kind, exc=err.exc, message=err.message, url=err.url, model=err.model, seconds=err.seconds, status=err.status, at=time.time())
    print("  (" + err.line() + ")")
    events.emit("sys", err.line())
    return err


# ---------- the call ----------
def is_warm(model):
    """Whether Ollama holds the model in memory right now (it answers in seconds); a cold one has to load first."""
    try:
        r = request("get", "/api/ps", timeout=CONNECT_SECONDS)
        return any(m.get("name") == model or m.get("model") == model for m in r.json().get("models", []))
    except (requests.RequestException, ValueError):
        return False


def abort(response):
    """Cut a streaming response off now. The socket is shut first: closing a response that is still mid-stream waits for the server otherwise."""
    if response is None:
        return
    try:
        sock = response.raw._connection.sock
        sock.shutdown(socket.SHUT_RDWR)
    except Exception:
        pass
    try:
        response.close()
    except Exception:
        pass


def stream_chat(body, model, warm, on_delta=None):
    """POST /api/chat with stream on. The timeout is the wait for the next chunk: FIRST_COLD or FIRST_WARM seconds for the first one, GAP_SECONDS
    after that, so a long answer is never cut off while it is still arriving. Returns (text, meta) or raises LocalError."""
    first_wait = FIRST_WARM if warm else FIRST_COLD
    q = queue.Queue()
    box = {}
    base = url()

    def worker():
        try:
            r = request("post", "/api/chat", json=body, stream=True, timeout=(CONNECT_SECONDS, first_wait + 5))
            box["r"] = r
            if r.status_code >= 400:
                q.put(("http", r.status_code, r.text))
                return
            for line in r.iter_lines():
                if line:
                    q.put(("chunk", line))
            q.put(("end",))
        except Exception as e:
            q.put(("exc", e))

    started = time.time()
    threading.Thread(target=worker, daemon=True).start()
    parts, meta, first_at = [], {}, None
    while True:
        try:
            item = q.get(timeout=GAP_SECONDS if first_at is not None else first_wait)
        except queue.Empty:
            abort(box.get("r"))
            raise timeout_error(model, time.time() - started, warm, first_at is not None)
        kind = item[0]
        if kind == "end":
            break
        if kind == "http":
            raise from_http(item[1], item[2], model, time.time() - started, warm)
        if kind == "exc":
            raise from_exception(item[1], model, time.time() - started, warm, first_wait, first_at is not None)
        if first_at is None:
            first_at = time.time() - started
        try:
            data = json.loads(item[1])
        except ValueError:
            continue
        if data.get("error"):
            raise from_http(500, str(data["error"]), model, time.time() - started, warm)
        piece = str((data.get("message") or {}).get("content", ""))
        if piece:
            parts.append(piece)
            if on_delta:
                on_delta(piece)
        if data.get("done"):
            meta = {k: data.get(k) for k in ("prompt_eval_count", "eval_count", "load_duration")}
            break
    meta.update(first_token=first_at or 0.0, seconds=time.time() - started, warm=warm, url=base, model=model)
    return "".join(parts), meta


def ok(meta):
    turn = LAST.get("turn")
    LAST.clear()
    if turn:
        LAST["turn"] = turn
    LAST.update(ok=True, kind="ok", message="answered", at=time.time(), **meta)


# ---------- a short prompt for plain chat ----------
def short_system(text=""):
    pet = config.PET_NAME
    parts = [f"You are {config.ASSISTANT}, a warm, honest voice assistant on the user's laptop. Replies are spoken aloud: one to three short plain sentences, no lists, "
             "no markdown. Say when you do not know and never claim to have done something you did not do.",
             f"Call the user {pet}." if pet else "",
             "Now: " + datetime.now().astimezone().strftime("%A %Y-%m-%d %H:%M") + ".",
             lang.reply_hint(text), profile.prompt_lines()]
    return " ".join(p for p in parts if p)


def is_chat_system(message):
    return message.get("role") == "system" and str(message.get("content", "")).startswith(f"You are {config.ASSISTANT}, a friendly voice companion")


def compact(messages):
    """The same conversation for the local model when it is plain chat: the short persona with the nickname and the time, the last four turns cut
    short, and the question. Anything else (a tool plan, a summary task) is passed through untouched."""
    if not messages or not is_chat_system(messages[0]):
        return messages
    last = messages[-1]
    want = lang.reply_language(str(last.get("content", "")))
    history = [m for m in messages[1:-1] if m.get("role") in ("user", "assistant") and lang.script(m.get("content", "")) == want][-HISTORY_MESSAGES:]
    trimmed = [{"role": m["role"], "content": str(m.get("content", ""))[:HISTORY_CHARS]} for m in history]
    question = dict(last)
    return [{"role": "system", "content": short_system(str(last.get("content", "")))}] + trimmed + [question]


def predict_cap(max_tokens, want_json):
    """num_predict for a local call: plain chat is capped near 200 tokens, drafts keep more room, tool plans keep what they asked for."""
    if want_json:
        return max_tokens
    return min(max_tokens, DRAFT_TOKENS if max_tokens >= 800 else CHAT_TOKENS)


# ---------- preload ----------
def preload(model, free=None, running=True):
    """Load the model into memory (and keep it for five minutes) so the first question is not the one that pays for it. Returns True when it is warm."""
    from ..actions import events
    if free is not None and free < MIN_FREE_GB:
        events.emit("sys", f"local model not preloaded: {free:.1f} GB free, it needs {MIN_FREE_GB} GB")
        return False
    state.update(warming=True, since=time.time(), model=model)
    started = time.time()
    try:
        r = request("post", "/api/generate", json={"model": model, "prompt": "", "keep_alive": KEEP_ALIVE, "stream": False}, timeout=(CONNECT_SECONDS, FIRST_COLD * 2))
        if r.status_code >= 400:
            raise from_http(r.status_code, r.text, model, time.time() - started, False)
        events.emit("sys", f"local model {model} is warm (loaded in {time.time() - started:.1f} s)")
        return True
    except LocalError as e:
        report(e)
    except requests.RequestException as e:
        report(from_exception(e, model, time.time() - started, False))
    finally:
        state["warming"] = False
    return False


def warming():
    return bool(state["warming"])


# ---------- the CPU belongs to the model while it generates ----------
listeners = []
_gen = {"n": 0}
_gen_lock = threading.Lock()


def generating():
    """True while any local call is running. The window drops to low power and pauses the cursor effects for exactly this time."""
    return _gen["n"] > 0


def _tell(on):
    for fn in list(listeners):
        try:
            fn(on)
        except Exception:
            pass


class Generation:
    """Context manager around one local call: marks the model as busy (the window listens) and times the turn."""

    def __enter__(self):
        self.t0 = time.time()
        with _gen_lock:
            _gen["n"] += 1
            first = _gen["n"] == 1
        if first:
            _tell(True)
        return self

    def __exit__(self, *exc):
        with _gen_lock:
            _gen["n"] = max(0, _gen["n"] - 1)
            last = _gen["n"] == 0
        if last:
            _tell(False)
        return False

    def throttled(self):
        """Whether a window really dropped to low power during this call (it stamps state['ui_throttled_at'] when it does)."""
        return state.get("ui_throttled_at", 0.0) >= self.t0


TURN_KEEP = 10


def _turns_path():
    return config.DATA / "local-turns.json"


def recent_turns():
    """The last 10 local turns, oldest first: {first (seconds to the first word, or None when none came), total, prompt, throttled, at}. Counts only, no text."""
    from ..core import jsonfile
    rows = jsonfile.read(_turns_path(), [], list)
    return [r for r in rows if isinstance(r, dict)][-TURN_KEEP:]


def record_turn(first, total, prompt, throttled):
    from ..core import jsonfile
    rows = recent_turns()
    rows.append({"first": None if first is None else round(float(first), 2), "total": round(float(total), 2), "prompt": int(prompt),
                 "throttled": bool(throttled), "at": int(time.time())})
    try:
        jsonfile.write(_turns_path(), rows[-TURN_KEEP:])
    except OSError:
        pass


def average_first_word():
    """(average seconds to the first word over the last 10 local turns that produced one, how many of the last 10 turns that is). (None, 0) before any."""
    rows = recent_turns()
    firsts = [r["first"] for r in rows if r.get("first") is not None]
    return (sum(firsts) / len(firsts) if firsts else None), len(firsts)


def log_turn(prompt_tokens, gen, meta=None, err=None):
    """One Activity line per local turn: prompt tokens, time to the first word, total time and whether the UI was throttled. It uses no word the
    window treats as a fault, so a slow turn does not turn the globe red."""
    from ..actions import events
    seconds = time.time() - gen.t0
    if meta:
        reported = meta.get("prompt_eval_count")
        prompt = f"prompt {reported} tokens" if reported else f"prompt about {prompt_tokens} tokens"
        first = f"first word {meta.get('first_token', 0.0):.1f} s ({'warm' if meta.get('warm') else 'cold'})"
    else:
        prompt = f"prompt about {prompt_tokens} tokens"
        first = f"no answer after {seconds:.1f} s ({err.kind})" if err else f"no answer after {seconds:.1f} s"
    ui = "UI throttled yes (15 fps, no particles, cursor effects paused)" if gen.throttled() else "UI throttled no"
    line = f"local model turn: {prompt}, {first}, total {seconds:.1f} s, {ui}"
    print("  (" + line + ")")
    events.emit("sys", line)
    record_turn((meta or {}).get("first_token") if meta else None, seconds, (meta or {}).get("prompt_eval_count") or prompt_tokens, gen.throttled())
    LAST["turn"] = {"prompt": prompt_tokens, "first": (meta or {}).get("first_token"), "total": round(seconds, 2), "throttled": gen.throttled()}
    return line
