"""Notes kept in the database with the window they were written from, plus a readable copy per topic."""
import re
from pathlib import Path
from datetime import date, datetime

from ..core import config
from . import memory, store

NOTES_DIR = Path(config.get("NOTES_DIR") or config.DATA / "notes").expanduser()
TERMINALS = ("konsole", "terminal", "jarvis", "xterm", "kitty", "alacritty")
TODAY_TOPICS = {"today", "todo", "to do", "tasks"}


def _slug(topic):
    return re.sub(r"[^a-z0-9]+", "-", str(topic).lower()).strip("-")[:40] or "general"


def derive_topic(text="", conversation=""):
    """A topic when the user gave none: an acronym in the text, the focused window, then the conversation."""
    m = re.search(r"\b[A-Z]{2,6}\b", str(text))
    if m:
        return m.group(0)
    try:
        from ..actions import windows
        win = windows.active_window()
    except Exception:
        win = None
    if win:
        app, title = win
        if not any(t in (app + title).lower() for t in TERMINALS):
            first = re.split(r"\s[—–-]\s", title)[0]
            words = re.findall(r"[A-Za-z0-9]+", first)[:4]
            if words:
                return " ".join(words)
    topics = memory._topics(conversation, 1) if conversation else ""
    return topics or "general"


def _write_copy(topic):
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTES_DIR / (_slug(topic) + ".txt")
    with store.db() as con:
        rows = con.execute("SELECT ts, text FROM notes WHERE lower(topic)=? ORDER BY id", (topic.lower(),)).fetchall()
    if rows:
        path.write_text("".join(f"[{r['ts'][:16].replace('T', ' ')}] {r['text']}\n" for r in rows))
    elif path.exists():
        path.unlink()
    return path


def save(topic, text, with_window=True):
    memory._boot()
    text = " ".join(str(text or "").split())[:2000]
    if not text:
        raise ValueError("empty note")
    topic = " ".join(str(topic or "").split())[:40] or "general"
    app = title = None
    if with_window:
        try:
            from ..actions import windows
            win = windows.active_window()
        except Exception:
            win = None
        if win:
            app, title = win[0] or None, win[1] or None
    with store.db() as con:
        con.execute("INSERT INTO notes(ts, topic, text, app, window_title) VALUES(?,?,?,?,?)",
                    (datetime.now().isoformat(timespec="seconds"), topic, text, app, title))
    _write_copy(topic)
    return topic


def topics():
    memory._boot()
    with store.db() as con:
        return [(r["topic"], r["n"]) for r in con.execute(
            "SELECT topic, COUNT(*) AS n FROM notes GROUP BY lower(topic) ORDER BY MAX(id) DESC")]


def _match(topic):
    asked = memory._words(topic)
    slug = _slug(topic)
    with store.db() as con:
        rows = con.execute("SELECT * FROM notes ORDER BY id").fetchall()
    return [r for r in rows if _slug(r["topic"]) == slug or asked & memory._words(r["topic"])]


def read(topic):
    memory._boot()
    return [r["text"] for r in _match(topic)]


def search(query):
    memory._boot()
    asked = memory._words(query)
    if not asked:
        return []
    with store.db() as con:
        rows = con.execute("SELECT * FROM notes ORDER BY id DESC").fetchall()
    return [(r["topic"], r["text"]) for r in rows if asked & memory._words(r["topic"] + " " + r["text"])][:8]


def delete(topic):
    rows = _match(topic)
    if not rows:
        return 0
    with store.db() as con:
        con.executemany("DELETE FROM notes WHERE id=?", [(r["id"],) for r in rows])
    for t in {r["topic"] for r in rows}:
        _write_copy(t)
    return len(rows)


def for_today():
    """Notes tagged for today: topic today or todo, or mentioning today or tonight, written in the last day."""
    memory._boot()
    cutoff = date.today().isoformat()
    with store.db() as con:
        rows = con.execute("SELECT topic, text, ts FROM notes ORDER BY id DESC LIMIT 100").fetchall()
    return [r["text"] for r in rows if r["topic"].lower() in TODAY_TOPICS
            or (r["ts"][:10] == cutoff and re.search(r"\b(today|tonight)\b", r["text"], re.I))]
