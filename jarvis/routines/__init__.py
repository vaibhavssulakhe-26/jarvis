"""Routines: small jobs Jarvis does on a schedule while you are away. They live in data/routines.md, one per line:

    - 08:00 | morning briefing | build the morning briefing

The file is parsed with plain code. A routine that was missed (laptop off) runs once at the next start. State is kept in
data/routines-state.json and a file lock stops two processes (the systemd timer and the app) from running the same job twice."""
import fcntl
import re
from contextlib import contextmanager
from datetime import datetime, timedelta

from ..core import config, jsonfile

LINE = re.compile(r"^\s*[-*]\s*(briefing-time|\d{1,2}:\d{2})\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*$")
ACTIONS = (("briefing", r"brief|morning|digest"), ("reindex", r"re-?index|index|notes"), ("triage", r"triage|inbox|e-?mail|mail"))
DEFAULT_FILE = """# Routines

One routine per line: `- HH:MM | name | instruction`. Edit this file freely.
`briefing-time` as the time means BRIEFING_TIME from .env (08:00 if unset).
Instructions Jarvis understands: briefing (build the morning briefing), triage (rank unread email, read only), reindex (notes and PDFs).

- briefing-time | morning briefing | build the morning briefing
- 23:00 | nightly inbox triage | triage unread email and save the result
- 23:30 | nightly notes reindex | reindex notes and PDFs
"""


def path():
    return config.DATA / "routines.md"


def state_path():
    return config.DATA / "routines-state.json"


def briefing_time():
    raw = config.get("BRIEFING_TIME", "08:00")
    return raw if re.fullmatch(r"\d{1,2}:\d{2}", raw) else "08:00"


def action_of(text):
    low = str(text).lower()
    return next((name for name, pattern in ACTIONS if re.search(pattern, low)), None)


def load():
    """[{time, name, instruction, action}] from data/routines.md, which is created with the defaults on first use."""
    p = path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(DEFAULT_FILE)
    out = []
    for line in p.read_text().splitlines():
        m = LINE.match(line)
        if not m:
            continue
        when = briefing_time() if m.group(1) == "briefing-time" else m.group(1)
        h, mi = (int(x) for x in when.split(":"))
        if h > 23 or mi > 59:
            continue
        out.append({"time": f"{h:02d}:{mi:02d}", "name": m.group(2), "instruction": m.group(3), "action": action_of(m.group(2) + " " + m.group(3))})
    return out


def add(when, name, instruction):
    """Append a routine. The instruction must map to something Jarvis can do."""
    if not re.fullmatch(r"\d{1,2}:\d{2}", when) or int(when.split(":")[0]) > 23 or int(when.split(":")[1]) > 59:
        raise ValueError("That time does not look right.")
    if action_of(name + " " + instruction) is None:
        raise ValueError("I can schedule a briefing, an inbox triage or a notes reindex.")
    name = re.sub(r"[|\n]", " ", name).strip()[:40] or "routine"
    instruction = re.sub(r"[|\n]", " ", instruction).strip()[:120]
    if any(r["name"].lower() == name.lower() for r in load()):
        raise ValueError(f"There is already a routine called {name}.")
    with path().open("a") as f:
        f.write(f"- {int(when.split(':')[0]):02d}:{when.split(':')[1]} | {name} | {instruction}\n")
    return name


def find(name):
    want = re.sub(r"[^a-z0-9 ]", "", str(name).lower()).strip()
    rows = load()
    for r in rows:
        if re.sub(r"[^a-z0-9 ]", "", r["name"].lower()) == want:
            return r
    hits = [r for r in rows if want and (want in r["name"].lower() or want in r["instruction"].lower() or r["action"] == action_of(want))]
    return hits[0] if hits else None


@contextmanager
def locked():
    """One process at a time may check and run routines."""
    lock = config.DATA / "routines.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _state():
    data = jsonfile.read(state_path(), {}, dict)
    data.setdefault("since", datetime.now().isoformat(timespec="seconds"))
    data.setdefault("last", {})
    return data


def _save(data):
    jsonfile.write(state_path(), data)


def occurrence(routine, now):
    """The most recent time this routine was scheduled to run, at or before now."""
    h, m = (int(x) for x in routine["time"].split(":"))
    at = now.replace(hour=h, minute=m, second=0, microsecond=0)
    return at if at <= now else at - timedelta(days=1)


def due(now=None, state=None):
    """Routines whose latest scheduled time has passed without a run since. A routine added today does not count older slots."""
    now = now or datetime.now()
    state = state or _state()
    since = datetime.fromisoformat(state["since"])
    out = []
    for r in load():
        last = datetime.fromisoformat(state["last"][r["name"]]) if r["name"] in state["last"] else since
        if r["action"] and last < occurrence(r, now):
            out.append(r)
    return out


def execute(routine):
    """Run one routine and return a short result line. Nothing here sends, deletes or moves mail."""
    action = routine["action"]
    if action == "briefing":
        from . import morning
        result = morning.build()
        return f"briefing saved ({result['source']})"
    if action == "triage":
        from . import triage
        return triage.run()
    if action == "reindex":
        from ..memory import rag
        n = rag.reindex()
        return f"notes reindexed ({n if isinstance(n, int) else 'done'})"
    raise ValueError("no handler")


def run_one(routine, now=None):
    """Run it now regardless of the clock and record the run."""
    now = now or datetime.now()
    try:
        line = execute(routine)
        ok = True
    except Exception as e:
        line, ok = f"failed ({type(e).__name__})", False
    with locked():
        data = _state()
        data["last"][routine["name"]] = now.isoformat(timespec="seconds")
        _save(data)
    print(f"  (routine {routine['name']}: {line})")
    return ok, line


def run_due(now=None):
    """Run what is due, one routine at a time. Returns [(name, ok, line)]."""
    now = now or datetime.now()
    done = []
    with locked():
        data = _state()
        _save(data)
        todo = due(now, data)
        for r in todo:
            data["last"][r["name"]] = now.isoformat(timespec="seconds")
        _save(data)
    for r in todo:
        ok, line = run_one(r, now)
        done.append((r["name"], ok, line))
    return done
