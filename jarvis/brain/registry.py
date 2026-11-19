"""The providers Jarvis can use, from real data only: what is configured, what the last real call did (never a ping), what a manual check found, the
primary and fallback order for the current mode, the selected model, capabilities, usage from data/usage.json and data/traces.jsonl, and recent errors.
Keys are never read into any value this module returns; only whether a key is set. Extra providers are added in .env: EXTRA_PROVIDERS=name1,name2 with
NAME_URL (an OpenAI-compatible base URL), NAME_API_KEY and NAME_MODEL."""
import re
import time

import requests

from .. import traces
from ..actions import stats
from ..core import config, jsonfile
from . import brain, local

BUILTIN = ("ollama", "groq", "openrouter")
LABELS = {"ollama": "Ollama (this laptop)", "groq": "Groq", "openrouter": "OpenRouter"}
CAPABILITIES = {
    "ollama": ["local and offline", "chat", "tool plans as JSON", "streaming"],
    "groq": ["chat", "native tool calling", "vision", "streaming", "larger tier for hard questions"],
    "openrouter": ["chat", "code (CODE_PROVIDER)", "many models"],
}
DEFAULT_URLS = {"groq": "https://api.groq.com/openai/v1", "openrouter": "https://openrouter.ai/api/v1"}
PROBES = {}
MODELS_TTL = 24 * 3600
PROBE_SECONDS = 8


def extra_names():
    names = [n.strip().lower() for n in config.get("EXTRA_PROVIDERS").split(",")]
    return [n for n in dict.fromkeys(names) if re.fullmatch(r"[a-z][a-z0-9_]{1,23}", n) and n not in BUILTIN]


def key_var(pid):
    return pid.upper() + "_API_KEY"


def key_set(pid):
    return bool(config.get(key_var(pid)))


def base_url(pid):
    if pid == "ollama":
        return local.url()
    return config.get(pid.upper() + "_URL") or DEFAULT_URLS.get(pid, "")


def default_model(pid):
    if pid == "ollama":
        return config.get("OLLAMA_MODEL") or brain._ollama_name.get("name") or brain.OLLAMA_DEFAULT
    if pid == "groq":
        return brain.MODEL
    if pid == "openrouter":
        return ", ".join(brain.OPENROUTER_MODELS)
    return config.get(pid.upper() + "_MODEL")


def selected_model(pid):
    """The model in use: the one chosen on the Models page, else the .env default."""
    return config.chosen(pid) or default_model(pid)


def select_model(pid, model):
    """Save the model choice (not a secret, so it lives in settings.json). An empty value goes back to the .env default."""
    if pid not in all_ids():
        raise ValueError(pid)
    path = config.DATA / "settings.json"
    data = jsonfile.read(path, {}, dict)
    models = data.get("models") if isinstance(data.get("models"), dict) else {}
    model = str(model or "").strip()[:120]
    if model:
        models[pid] = model
    else:
        models.pop(pid, None)
    data["models"] = models
    jsonfile.write(path, data)
    return selected_model(pid)


def all_ids():
    return list(BUILTIN) + extra_names()


def configured(pid):
    """Set up in config: Ollama always (it needs no key), a cloud provider when its key is set (and, for an extra one, its URL)."""
    if pid == "ollama":
        return True
    if pid == "openrouter" or pid == "groq":
        return key_set(pid)
    return key_set(pid) and bool(base_url(pid))


def order():
    """[(provider, role)] for the current mode: who answers first and who is the backup."""
    mode = config.brain_mode()
    extras = [(n, "fallback") for n in extra_names() if configured(n)]
    if mode == "offline":
        return [("ollama", "primary")]
    if mode == "hybrid":
        return [("groq", "primary"), ("openrouter", "fallback")] + extras + [("ollama", "fallback")]
    return [("ollama", "primary"), ("groq", "advanced"), ("openrouter", "advanced")] + [(n, "advanced") for n, _ in extras]


def role(pid):
    return next((r for p, r in order() if p == pid), "off")


def usage(pid):
    """{'calls', 'tokens', 'today_calls', 'week_calls', 'traces', 'ok', 'failed', 'avg_ms'}: counts from usage.json (answered requests) and the trace file."""
    total, today = stats.usage(7)
    week = total.get(pid, {})
    now = today.get(pid, {})
    rows = [r for r in traces.load(500) if r.get("provider") == pid]
    ok = sum(1 for r in rows if r.get("ok", True))
    lat = [r.get("latency_ms", 0) for r in rows if r.get("latency_ms")]
    return {"calls": int(week.get("calls", 0)), "tokens": int(week.get("tokens", 0)), "today_calls": int(now.get("calls", 0)),
            "traces": len(rows), "ok": ok, "failed": len(rows) - ok, "avg_ms": int(sum(lat) / len(lat)) if lat else 0}


def errors(pid, limit=3):
    """The last real failure of the provider (from the live health record) and the last few failed requests it was part of."""
    out = []
    why = brain.why_down(pid) if pid in brain.LABELS else ""
    if why:
        out.append(why)
    for r in reversed([r for r in traces.load(500) if r.get("provider") == pid and not r.get("ok", True)]):
        text = r.get("error") or r.get("reason")
        if text and text not in out:
            out.append(str(text))
        if len(out) >= limit:
            break
    return out[:limit]


def state(pid):
    """(level, text) of the last real call: ok, bad or idle. A provider the brain does not route through says it has not been used."""
    if pid in brain.LABELS:
        return brain.provider_state(pid)
    h = brain.HEALTH.get(pid)
    if h is None:
        return "idle", "not called yet this session"
    return ("ok", "last call worked") if h["ok"] else ("bad", "last call failed, it " + (h.get("why") or brain._cause(h["code"])))


def probe(pid):
    """A manual check, only when the user asks: one small GET to the provider. The key goes in a header and never into the result."""
    started = time.time()
    try:
        if pid == "ollama":
            r = local.request("get", "/api/tags", timeout=PROBE_SECONDS)
        else:
            headers = {"Authorization": "Bearer " + config.get(key_var(pid))} if key_set(pid) else {}
            r = requests.get(base_url(pid).rstrip("/") + "/models", headers=headers, timeout=PROBE_SECONDS, proxies={"http": None, "https": None} if pid == "ollama" else None)
        ok = r.status_code < 400
        detail = "answered" if ok else f"HTTP {r.status_code}" + (" (the key was refused)" if r.status_code in (401, 403) else "")
    except requests.RequestException as e:
        ok, detail = False, type(e).__name__
    PROBES[pid] = {"ok": ok, "detail": detail, "at": time.time(), "seconds": round(time.time() - started, 1)}
    return PROBES[pid]


def reachable(pid):
    """'reachable', 'not reachable: <why>' or 'not checked' from the last manual check."""
    p = PROBES.get(pid)
    if not p:
        return "not checked"
    return "reachable" if p["ok"] else "not reachable: " + p["detail"]


def installed_models(pid="ollama"):
    """Models Ollama reports installed (a real call when asked), or []."""
    if pid != "ollama":
        return []
    try:
        r = local.request("get", "/api/tags", timeout=3)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return []


def openrouter_models(refresh=False):
    """[{'id', 'name', 'free', 'context'}] for the picker. Fetched when asked and kept in data/openrouter-models.json for a day. [] when it cannot be fetched."""
    path = config.DATA / "openrouter-models.json"
    cached = jsonfile.read(path, {}, dict)
    if not refresh and cached.get("models") and time.time() - float(cached.get("at", 0)) < MODELS_TTL:
        return cached["models"]
    try:
        r = requests.get(base_url("openrouter").rstrip("/") + "/models", timeout=PROBE_SECONDS)
        r.raise_for_status()
        models = []
        for m in r.json().get("data", []):
            mid = str(m.get("id") or "")
            if not mid:
                continue
            price = m.get("pricing") or {}
            models.append({"id": mid, "name": str(m.get("name") or mid)[:80], "context": int(m.get("context_length") or 0),
                           "free": mid.endswith(":free") or str(price.get("prompt", "1")) in ("0", "0.0")})
        models.sort(key=lambda m: (not m["free"], m["id"]))
        jsonfile.write(path, {"at": time.time(), "models": models})
        return models
    except (requests.RequestException, ValueError, TypeError):
        return cached.get("models") or []


def describe(pid):
    """Everything the Models page shows for one provider. No key, ever."""
    level, text = state(pid)
    return {"id": pid, "label": LABELS.get(pid, pid.capitalize()), "builtin": pid in BUILTIN, "configured": configured(pid), "key_var": key_var(pid) if pid != "ollama" else "",
            "key_set": key_set(pid) if pid != "ollama" else None, "url": base_url(pid), "model": selected_model(pid), "role": role(pid), "level": level, "last_call": text,
            "reachable": reachable(pid), "capabilities": CAPABILITIES.get(pid, ["chat (OpenAI-compatible)"]), "usage": usage(pid), "errors": errors(pid)}


def providers():
    return [describe(pid) for pid in all_ids()]


def where_keys():
    return f"API keys are entered only in {config.ENV_FILE} (for example {key_var('groq')}=...), never here. Restart Jarvis after editing it."
