"""Chat threads: one shared conversation for typed and spoken messages, saved redacted in data/chats/<id>.json.
`attach()` listens to the event bus ("you", "jarvis", "tier"), so anything said or typed lands in the current thread."""
import threading
import time
from datetime import datetime

from .. import redact
from ..actions import events
from ..core import config, jsonfile

KEEP = 400
SUMMARY_CHARS = 500
_lock = threading.RLock()
_cur = {"id": None, "tier": "", "pending": None}
changed = []


def folder():
    return config.DATA / "chats"


def _path(tid):
    return folder() / f"{tid}.json"


def _stamp():
    return datetime.now().isoformat(timespec="seconds")


def _blank():
    tid = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return {"id": tid, "title": "New chat", "created": _stamp(), "updated": _stamp(), "extracted": 0, "messages": []}


def _notify(kind, **info):
    for fn in list(changed):
        try:
            fn(kind, info)
        except Exception:
            pass


def save(thread):
    thread["updated"] = _stamp()
    jsonfile.write(_path(thread["id"]), thread)


def load(tid):
    data = jsonfile.read(_path(tid), None, dict)
    return data if data and isinstance(data.get("messages"), list) else None


def listing():
    """[{id, title, updated, count}] newest first."""
    rows = []
    try:
        names = sorted(folder().glob("*.json"))
    except OSError:
        return rows
    for p in names:
        t = jsonfile.read(p, None, dict)
        if t and "messages" in t:
            rows.append({"id": t.get("id", p.stem), "title": t.get("title", "Chat"), "updated": t.get("updated", ""), "count": len(t["messages"])})
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def current():
    """The thread being written to: the last one used, or a new one when there is none yet."""
    with _lock:
        t = load(_cur["id"]) if _cur["id"] else None
        if t is None:
            rows = listing()
            t = load(rows[0]["id"]) if rows else None
        if t is None:
            t = _blank()
        _cur["id"] = t["id"]
        return t


def new_chat():
    """Start an empty thread. The one being left is mined for facts first (see facts.extract_thread)."""
    with _lock:
        old = current()
        t = _blank()
        _cur["id"] = t["id"]
        save(t)
    _notify("new", id=t["id"], old=old["id"])
    return t


def switch(tid):
    with _lock:
        t = load(tid)
        if t is None:
            return None
        _cur["id"] = tid
    _notify("switch", id=tid)
    return t


def delete(tid):
    with _lock:
        try:
            _path(tid).unlink()
        except OSError:
            pass
        if _cur["id"] == tid:
            _cur["id"] = None
    _notify("delete", id=tid)


def add(role, text, via="spoken", tier=""):
    """Append one message (redacted) and return it. Empty text is ignored."""
    text = redact.mask(str(text)).strip()
    if not text:
        return None
    with _lock:
        t = current()
        msg = {"role": role, "text": text, "at": _stamp(), "via": via}
        if tier:
            msg["tier"] = tier
        t["messages"].append(msg)
        del t["messages"][:-KEEP]
        if t["title"] == "New chat" and role == "user":
            t["title"] = text[:48]
        save(t)
    _notify("message", id=t["id"], message=msg)
    return msg


def on_event(kind, text):
    if kind == "tier":
        _cur["tier"] = text
    elif kind == "you":
        via = events.via[0]
        events.via[0] = "spoken"
        add("user", text, via)
    elif kind == "jarvis":
        tier, _cur["tier"] = _cur["tier"], ""
        add("assistant", text, tier=tier)


def attach():
    if on_event not in events.listeners:
        events.listeners.append(on_event)


def active():
    """True when the thread recorder is listening, so chat history comes from the thread."""
    return on_event in events.listeners


def detach():
    if on_event in events.listeners:
        events.listeners.remove(on_event)


def summary(old):
    """A plain summary of older messages: what the user said, one clipped phrase each. No model call."""
    bits = []
    for m in old:
        if m["role"] == "user":
            line = " ".join(m["text"].split())[:70]
            bits.append(line)
    text = "; ".join(bits)
    while len(text) > SUMMARY_CHARS and bits:
        bits.pop(0)
        text = "; ".join(bits)
    return text


def context(turns=12, per_message=700, skip_last=None):
    """Messages for the model: the last `turns` turns (user and assistant pairs, 2 * turns messages) and, when the thread is longer, a
    one-line summary of what came before. `skip_last` drops the final user message when it is the question being answered now."""
    msgs = [m for m in current()["messages"] if m["role"] in ("user", "assistant")]
    if skip_last and msgs and msgs[-1]["role"] == "user" and msgs[-1]["text"].strip() == redact.mask(str(skip_last)).strip():
        msgs = msgs[:-1]
    keep = msgs[-2 * turns:]
    old = msgs[:-2 * turns]
    out = []
    if old:
        out.append({"role": "system", "content": "Earlier in this conversation the user said: " + summary(old)})
    out += [{"role": m["role"], "content": m["text"][:per_message]} for m in keep]
    return out


def user_texts(thread=None, start=0):
    t = thread or current()
    return [m["text"] for m in t["messages"][start:] if m["role"] == "user"]


def idle_seconds():
    t = current()
    if not t["messages"]:
        return 0.0
    try:
        return time.time() - datetime.fromisoformat(t["messages"][-1]["at"]).timestamp()
    except ValueError:
        return 0.0
