"""What Jarvis remembers: facts, people, episode summaries and archived turns, in data/memory.db.

The user's own names come only from .env. Nothing said in conversation can change them."""
import json
import re
import threading
from collections import Counter
from datetime import datetime, timedelta

from ..core import config
from . import store

MAX_TURNS = 2000
SUMMARY_EVERY = 12
FACT_LIMIT = 5
EPISODE_LIMIT = 2
BLOCK_CHARS = 900

RELATIONS = ("dad father papa mom mother mummy mama brother sister wife husband friend uncle aunt cousin "
             "grandfather grandmother grandpa grandma son daughter roommate teacher professor boss colleague "
             "girlfriend boyfriend neighbour neighbor").split()
_REL = "(?:" + "|".join(RELATIONS) + ")"
_NAME = r"([a-z][\w'-]*(?: [a-z][\w'-]*){0,2})"
_STOP_NAME = {"and", "but", "who", "he", "she", "is", "was", "he's", "she's", "they", "which", "that", "because"}
_PRONOUNS = {"he", "she", "it", "this", "that", "who", "there", "they", "him", "her", "i", "you", "we"}
OTHER_PERSON = [
    (re.compile(rf"\b{_REL}(?:'s|s)? (?:full |first |real )?name(?: is|:)? {_NAME}", re.I), None),
    (re.compile(rf"\b{_NAME} is (?:my|his|her|their) ({_REL})\b", re.I), "swap"),
    (re.compile(rf"\bmy ({_REL}) (?:is )?(?:called|named) {_NAME}", re.I), "swap2"),
]
NAMEY = re.compile(r"\b(my name|name is|names|call me|called|nickname|known as|goes by|named|full name|"
                   r"surname|short name|pet name)\b", re.I)
CHIT = re.compile(r"^(hi|hello|hey|thanks|thank you|ok|okay|good (morning|night|evening|afternoon)|bye|"
                  r"how are you|what s up|who are you|yes|no|sure|cool|nice)\b")
_STOP = set("the a an and or to of in on at is it for my me you your i that this with was are be have has had "
            "what when where which who how do does did can could would will about from by not but so if".split())
_lock = threading.Lock()
_booted = [False]
_summarising = threading.Lock()


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _words(text):
    out = set()
    for w in re.findall(r"[a-z0-9]{3,}", str(text).lower()):
        if w in _STOP:
            continue
        for suffix in ("ing", "es", "s"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[:-len(suffix)]
                break
        out.add(w)
    return out


def _topics(text, n=5):
    words = [w for w in re.findall(r"[a-z]{4,}", str(text).lower()) if w not in _STOP]
    return ", ".join(w for w, _ in Counter(words).most_common(n))


def _clean_name(raw):
    parts = []
    for w in raw.strip().split():
        if w.lower() in _STOP_NAME:
            break
        parts.append(w)
    return " ".join(p.capitalize() for p in parts)


def other_person(text):
    """(name, relation) when the sentence names somebody else, such as my dad's name is X."""
    for pattern, order in OTHER_PERSON:
        m = pattern.search(str(text))
        if not m:
            continue
        if order is None:
            rel = re.search(_REL, m.group(0), re.I).group(0)
            name = m.group(1)
        elif order == "swap":
            name, rel = m.group(1), m.group(2)
        else:
            rel, name = m.group(1), m.group(2)
        name = _clean_name(name)
        if name and name.lower() not in _PRONOUNS:
            return name, rel.lower()
    return None


def judge(fact, key=""):
    """Decide what to do with a proposed fact: ("person", (name, relation)), ("reject", why) or ("fact", None)."""
    text = f"{key} {fact}"
    person = other_person(text)
    if person:
        return "person", person
    if NAMEY.search(text) or re.search(r"\bname\b", str(key), re.I):
        return "reject", "names"
    return "fact", None


def _category(text):
    t = str(text).lower()
    if re.search(r"\b(like|love|prefer|favou?rite|enjoy|hate)\b", t):
        return "preference"
    if re.search(r"\b(project|working on|building|studying|exam|college)\b", t):
        return "project"
    if re.search(r"\b(every|daily|usually|morning|night|routine|weekend)\b", t):
        return "routine"
    return "general"


def _key(fact):
    return "-".join(re.findall(r"[a-z0-9]+", str(fact).lower())[:8])


def _boot():
    if _booted[0]:
        return
    _booted[0] = True
    try:
        migrate()
    except Exception as e:
        print(f"  (memory migration failed: {type(e).__name__})")


def add_person(name, relation="", notes=""):
    with store.db() as con:
        row = con.execute("SELECT id FROM people WHERE lower(name)=? AND lower(relation)=?",
                          (name.lower(), relation.lower())).fetchone()
        if row:
            if notes:
                con.execute("UPDATE people SET notes=? WHERE id=?", (notes, row["id"]))
        else:
            con.execute("INSERT INTO people(name, relation, notes, created) VALUES(?,?,?,?)",
                        (name, relation, notes, _now()))


def remember(fact, key="", category="", source="chat"):
    """Store something lasting. Returns ("fact" | "person" | "reject", message to speak)."""
    _boot()
    fact = " ".join(str(fact or "").split())
    if not fact:
        return "reject", "I did not catch what to remember."
    kind, info = judge(fact, key)
    if kind == "person":
        name, relation = info
        add_person(name, relation)
        return "person", f"Okay, I noted that your {relation} is {name}. That does not change what I call you."
    if kind == "reject":
        who = config.PET_NAME or "you"
        return "reject", f"I keep your name as it is, so I will go on calling you {who}."
    key = str(key or "").strip() or _key(fact)
    now = _now()
    with store.db() as con:
        row = con.execute("SELECT id FROM facts WHERE key=? OR lower(value)=?", (key, fact.lower())).fetchone()
        if row:
            con.execute("UPDATE facts SET value=?, updated=? WHERE id=?", (fact, now, row["id"]))
        else:
            con.execute("INSERT INTO facts(key, value, category, source, created, updated) VALUES(?,?,?,?,?,?)",
                        (key, fact, category or _category(fact), source, now, now))
    return "fact", "Got it, I will remember that."


def top_facts(limit=FACT_LIMIT):
    _boot()
    with store.db() as con:
        return [r["value"] for r in con.execute("SELECT value FROM facts ORDER BY updated DESC, id DESC LIMIT ?",
                                                (limit,))]


def find_facts(query, limit=3):
    """Facts and people that share words with the query, best first: [(kind, id, text)]."""
    _boot()
    asked = _words(query)
    out = []
    with store.db() as con:
        for r in con.execute("SELECT id, key, value FROM facts"):
            score = len(asked & _words(r["key"] + " " + r["value"]))
            if score:
                out.append((score, "fact", r["id"], r["value"]))
        for r in con.execute("SELECT id, name, relation FROM people"):
            score = len(asked & _words(r["name"] + " " + r["relation"]))
            if score:
                out.append((score, "person", r["id"], f"your {r['relation']} {r['name']}".replace("  ", " ")))
    out.sort(key=lambda x: -x[0])
    return [(k, i, t) for _, k, i, t in out[:limit]]


def delete(kind, row_id):
    with store.db() as con:
        con.execute("DELETE FROM " + ("facts" if kind == "fact" else "people") + " WHERE id=?", (row_id,))


def people_summary():
    with store.db() as con:
        return [f"{r['name']} ({r['relation']})" if r["relation"] else r["name"]
                for r in con.execute("SELECT name, relation FROM people ORDER BY id DESC LIMIT 5")]


def episodes_on(day):
    _boot()
    with store.db() as con:
        return [r["summary"] for r in con.execute(
            "SELECT summary FROM episodes WHERE substr(ts,1,10)=? ORDER BY id", (day.isoformat(),))]


def context(text):
    """The compact memory block for one request. Chit-chat gets only the fixed identity line."""
    _boot()
    lines = []
    if config.PET_NAME:
        lines.append("Address the user only as " + config.PET_NAME + ". Never adopt or change their name "
                     "from conversation; names of other people are not theirs.")
    t = re.sub(r"[^a-z ]", " ", str(text).lower()).strip()
    if len(t.split()) <= 2 or CHIT.match(" ".join(t.split())):
        return "\n".join(lines)
    asked = _words(text)
    if not asked:
        return "\n".join(lines)
    with store.db() as con:
        facts = [(len(asked & _words(r["key"] + " " + r["value"])), r["value"])
                 for r in con.execute("SELECT key, value FROM facts")]
        eps = [(len(asked & _words(r["summary"] + " " + (r["topics"] or ""))), r["ts"], r["summary"])
               for r in con.execute("SELECT ts, summary, topics FROM episodes ORDER BY id DESC LIMIT 60")]
    facts = [v for s, v in sorted(facts, key=lambda x: -x[0]) if s][:FACT_LIMIT]
    eps.sort(key=lambda x: x[1], reverse=True)
    eps.sort(key=lambda x: -x[0])
    eps = [(ts, s) for sc, ts, s in eps if sc][:EPISODE_LIMIT]
    block = []
    if facts:
        block.append("Remembered about the user:\n" + "\n".join("- " + f for f in facts))
    if eps:
        block.append("Earlier conversations:\n" + "\n".join(f"- {ts[:10]}: {s}" for ts, s in eps))
    if block:
        lines.append("\n".join(block)[:BLOCK_CHARS])
    return "\n".join(lines)


# ---------- archived turns and episode summaries ----------
def _plain(role, text):
    if role == "assistant":
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                return str(data.get("say") or "").strip()
        except ValueError:
            pass
    return str(text).strip()


def archive_turns(turns):
    _boot()
    rows = [(_now(), role, _plain(role, text)[:600]) for role, text in turns]
    rows = [r for r in rows if r[2]]
    if not rows:
        return
    with store.db() as con:
        con.executemany("INSERT INTO turns(ts, role, text) VALUES(?,?,?)", rows)
    if pending_turns() >= SUMMARY_EVERY:
        threading.Thread(target=summarise_pending, daemon=True).start()


def pending_turns():
    upto = int(store.get_meta("summarised_upto", 0))
    with store.db() as con:
        return con.execute("SELECT COUNT(*) AS n FROM turns WHERE id>?", (upto,)).fetchone()["n"]


def summarise_pending():
    """One short episode summary for the turns not yet summarised. Nothing is deleted before it exists."""
    from ..brain import brain
    if not _summarising.acquire(blocking=False):
        return False
    try:
        upto = int(store.get_meta("summarised_upto", 0))
        with store.db() as con:
            rows = con.execute("SELECT id, ts, role, text FROM turns WHERE id>? ORDER BY id LIMIT 40",
                               (upto,)).fetchall()
        if len(rows) < 2:
            return False
        talk = "\n".join(f"{r['role']}: {r['text'][:200]}" for r in rows)
        summary = brain.ask("Summarise this conversation in one short paragraph of at most 50 words. "
                            "Keep only facts and decisions.\n" + talk, 120)
        summary = " ".join(summary.split())
        if not summary:
            return False
        with store.db() as con:
            con.execute("INSERT INTO episodes(ts, summary, topics) VALUES(?,?,?)",
                        (rows[0]["ts"], summary, _topics(talk)))
        store.set_meta("summarised_upto", rows[-1]["id"])
        _cap_turns()
        return True
    finally:
        _summarising.release()


def _cap_turns():
    upto = int(store.get_meta("summarised_upto", 0))
    with store.db() as con:
        extra = con.execute("SELECT COUNT(*) AS n FROM turns").fetchone()["n"] - MAX_TURNS
        if extra > 0:
            con.execute("DELETE FROM turns WHERE id IN (SELECT id FROM turns WHERE id<=? ORDER BY id LIMIT ?)",
                        (upto, extra))


def day_from_words(text):
    t = str(text).lower()
    today = datetime.now().date()
    if "yesterday" in t:
        return today - timedelta(days=1)
    if "today" in t or "this morning" in t:
        return today
    import dateparser
    cleaned = re.sub(r"\b(what|did|we|talk|about|on|the|discuss|discussed|last)\b", " ", t)
    when = dateparser.parse(cleaned.strip() or "today", settings={"PREFER_DATES_FROM": "past"})
    return when.date() if when else None


# ---------- one-time import of the old files ----------
def migrate():
    _booted[0] = True
    if store.get_meta("migrated"):
        return
    path = config.get("MEMORY_FILE", "data/memory.json")
    from pathlib import Path
    old = Path(path).expanduser()
    if not old.is_absolute():
        old = config.ROOT / old
    try:
        facts = json.loads(old.read_text()).get("facts", [])
    except (OSError, ValueError, AttributeError):
        facts = []
    for fact in facts:
        if str(fact).strip():
            remember(str(fact), source="migrated")
    notes = config.DATA / "notes"
    if notes.is_dir():
        with store.db() as con:
            for f in sorted(notes.glob("*.txt")):
                for line in f.read_text(errors="replace").splitlines():
                    m = re.match(r"\[([^\]]+)\] (.*)", line)
                    if line.strip():
                        con.execute("INSERT INTO notes(ts, topic, text) VALUES(?,?,?)",
                                    (m.group(1) if m else _now(), f.stem, m.group(2) if m else line.strip()))
    store.set_meta("migrated", _now())
