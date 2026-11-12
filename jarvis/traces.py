"""One JSON line per request in data/traces.jsonl: when, what was heard, how it was routed, which tool and brain, tokens, latency and
whether it worked. A request is marked "corrected" when the next sentence repeats it or contradicts it. The file is rotated at 5 MB.
The text is what you said, so the file stays on this laptop (data/ is git-ignored)."""
import difflib
import json
import re
import threading
import time
from datetime import datetime

from . import redact
from .core import config

MAX_BYTES = 5 * 1024 * 1024
CORRECT_WITHIN = 90
REPEAT_RATIO = 0.82
CONTRADICT = re.compile(r"^(?:no+|nope|not that|wrong|that'?s (?:not|wrong)|that is (?:not|wrong)|i said|i meant|i didn'?t (?:say|ask)|"
                        r"actually|not what i (?:asked|said|meant)|you misheard|try again|again)\b", re.I)
_lock = threading.RLock()
_current = {}
_last = {"heard": "", "at": 0.0, "id": 0}
_counter = [int(time.time())]


def path():
    return config.DATA / "traces.jsonl"


def enabled():
    return config.flag("TRACES", True)


def begin(heard, answering=False):
    """Start a trace for one request. `answering` is True when the sentence replies to a question Jarvis just asked."""
    _current.clear()
    if not enabled():
        return
    _counter[0] += 1
    _current.update(id=_counter[0], t0=time.time(), time=datetime.now().isoformat(timespec="seconds"), heard=redact.mask(heard)[:200], route="",
                    tool="", provider="", tokens=0, ok=True, corrected=False)
    if not answering and is_correction(heard, _last["heard"], time.time() - _last["at"]):
        mark_corrected(_last["id"])


def is_correction(text, previous, age):
    """True when text contradicts the previous request, or repeats it (three words or more with the same numbers, so "next" twice is fine), shortly after."""
    if not previous or age > CORRECT_WITHIN:
        return False
    a, b = _norm(text), _norm(previous)
    if not a or not b:
        return False
    if CONTRADICT.match(str(text).strip()):
        return True
    if len(a.split()) < 3 or re.findall(r"\d+", a) != re.findall(r"\d+", b):
        return False
    return difflib.SequenceMatcher(None, a, b).ratio() >= REPEAT_RATIO


def _norm(text):
    return re.sub(r"[^a-z0-9 ]", "", str(text).lower()).strip()


def note(**fields):
    """Add what is known so far to the open trace (route, tool, provider)."""
    if _current:
        _current.update({k: v for k, v in fields.items() if v not in (None, "")})


def add_tokens(n):
    if _current:
        _current["tokens"] = _current.get("tokens", 0) + int(n)


def fail(reason=""):
    if _current:
        _current["ok"] = False
        if reason:
            _current["reason"] = redact.mask(reason)[:80]


def end():
    """Write the open trace."""
    if not _current:
        return None
    line = {k: v for k, v in _current.items() if k != "t0"}
    line["latency_ms"] = round((time.time() - _current["t0"]) * 1000)
    _last.update(heard=line["heard"], at=time.time(), id=line["id"])
    _current.clear()
    append(line)
    return line


def append(line):
    with _lock:
        p = path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            if p.exists() and p.stat().st_size >= MAX_BYTES:
                p.replace(p.with_name(p.name + ".1"))
            with p.open("a") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError:
            pass


def mark_corrected(trace_id):
    """Rewrite the matching line, which is normally the last one, with corrected: true."""
    with _lock:
        p = path()
        try:
            lines = p.read_text().splitlines()
        except OSError:
            return False
        for i in range(len(lines) - 1, max(-1, len(lines) - 6), -1):
            try:
                row = json.loads(lines[i])
            except ValueError:
                continue
            if row.get("id") == trace_id:
                row["corrected"] = True
                lines[i] = json.dumps(row, ensure_ascii=False)
                p.write_text("\n".join(lines) + "\n")
                return True
    return False


def load(limit=None):
    """Traces, oldest first, from the rotated file and the current one."""
    rows = []
    for p in (path().with_name(path().name + ".1"), path()):
        try:
            for line in p.read_text().splitlines():
                try:
                    rows.append(json.loads(line))
                except ValueError:
                    continue
        except OSError:
            continue
    return rows[-limit:] if limit else rows


def failures(n=10, rows=None):
    """The last n requests that failed or were corrected, newest first."""
    rows = load() if rows is None else rows
    return [r for r in reversed(rows) if not r.get("ok", True) or r.get("corrected")][:n]


def describe(row):
    why = "corrected" if row.get("corrected") else row.get("reason") or "failed"
    return f"{row.get('time', '')[5:16].replace('T', ' ')}  {row.get('heard', '')[:50]!r}  {row.get('route', '') or '?'}  {row.get('tool', '') or '-'}  ({why})"
