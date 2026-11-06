"""The sqlite file behind memory, notes, reminder history, watches, sender scores and screen time."""
import sqlite3
import threading
from contextlib import contextmanager

from ..core import config

PATH = config.DATA / "memory.db"
_lock = threading.RLock()
_ready = set()

SCHEMA = """
CREATE TABLE IF NOT EXISTS facts(id INTEGER PRIMARY KEY, key TEXT, value TEXT, category TEXT,
    source TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS people(id INTEGER PRIMARY KEY, name TEXT, relation TEXT, notes TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS episodes(id INTEGER PRIMARY KEY, ts TEXT, summary TEXT, topics TEXT);
CREATE TABLE IF NOT EXISTS turns(id INTEGER PRIMARY KEY, ts TEXT, role TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS notes(id INTEGER PRIMARY KEY, ts TEXT, topic TEXT, text TEXT, app TEXT, window_title TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
CREATE TABLE IF NOT EXISTS reminder_events(id INTEGER PRIMARY KEY, ts TEXT, text TEXT, outcome TEXT,
    due TEXT, acted TEXT);
CREATE TABLE IF NOT EXISTS watches(id INTEGER PRIMARY KEY, target TEXT, kind TEXT, interval INTEGER,
    condition TEXT, last_hash TEXT, last_summary TEXT, last_run REAL, paused INTEGER DEFAULT 0, created TEXT);
CREATE TABLE IF NOT EXISTS senders(sender TEXT PRIMARY KEY, score INTEGER);
CREATE TABLE IF NOT EXISTS screen_minutes(day TEXT, category TEXT, minutes REAL, PRIMARY KEY(day, category));
"""


@contextmanager
def db():
    """A connection that commits on success. One writer at a time keeps the threads from clashing."""
    with _lock:
        PATH.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(PATH, timeout=5)
        con.row_factory = sqlite3.Row
        try:
            if str(PATH) not in _ready:
                con.executescript(SCHEMA)
                _ready.add(str(PATH))
            yield con
            con.commit()
        finally:
            con.close()


def get_meta(key, default=None):
    with db() as con:
        row = con.execute("SELECT v FROM meta WHERE k=?", (key,)).fetchone()
    return row["v"] if row else default


def set_meta(key, value):
    with db() as con:
        con.execute("INSERT OR REPLACE INTO meta(k, v) VALUES(?, ?)", (key, str(value)))


def claim(key, value):
    """Set a meta key to value only if it is not already that value. True when this caller changed it.
    Lets two processes agree on who does a once-a-day job."""
    with db() as con:
        cur = con.execute("UPDATE meta SET v=? WHERE k=? AND v!=?", (str(value), key, str(value)))
        if cur.rowcount:
            return True
        cur = con.execute("INSERT OR IGNORE INTO meta(k, v) VALUES(?, ?)", (key, str(value)))
        return cur.rowcount > 0
