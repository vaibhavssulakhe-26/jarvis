"""One view of everything Jarvis remembers, for the Memory page: the long-term facts (data/memory.jsonl), the facts and people in data/memory.db and the
conversation summaries. Each entry has a ref such as "facts:ab12cd34ef" that names its store and row, so it can be opened, edited and deleted."""
import re
from dataclasses import dataclass

from . import controls, facts, memory, store

STORE_LABEL = {"facts": "long-term", "memory": "facts", "people": "people", "episodes": "conversations"}
EDITABLE_CATEGORIES = controls.NORMAL
MAX_TEXT = 400


@dataclass
class Entry:
    ref: str
    store: str
    date: str
    category: str
    text: str


def _fact_category(kind):
    return kind if kind in controls.CATEGORIES else "fact"


def _memory_category(cat):
    return {"general": "fact"}.get(cat, cat if cat in controls.CATEGORIES else "fact")


def entries():
    """Every memory, newest first."""
    out = []
    for r in facts.load():
        out.append(Entry("facts:" + str(r.get("id")), "facts", str(r.get("date", "")), _fact_category(r.get("kind")), r["text"]))
    memory._boot()
    with store.db() as con:
        for r in con.execute("SELECT id, value, category, updated FROM facts"):
            out.append(Entry(f"memory:{r['id']}", "memory", str(r["updated"] or "")[:10], _memory_category(r["category"]), str(r["value"])))
        for r in con.execute("SELECT id, name, relation, created FROM people"):
            text = f"{r['name']} ({r['relation']})" if r["relation"] else str(r["name"])
            out.append(Entry(f"people:{r['id']}", "people", str(r["created"] or "")[:10], "people", text))
        for r in con.execute("SELECT id, ts, summary FROM episodes"):
            out.append(Entry(f"episodes:{r['id']}", "episodes", str(r["ts"] or "")[:10], "conversation", str(r["summary"])))
    out.sort(key=lambda e: (e.date, e.ref), reverse=True)
    return out


def categories_present(items=None):
    return sorted({e.category for e in (items if items is not None else entries())})


def search(query="", category="", items=None):
    """Entries whose text contains every word of the query (any case), optionally of one category."""
    words = re.findall(r"\w+", str(query).lower())
    out = []
    for e in (items if items is not None else entries()):
        if category and e.category != category:
            continue
        text = e.text.lower() + " " + e.category
        if all(w in text for w in words):
            out.append(e)
    return out


def get(ref):
    return next((e for e in entries() if e.ref == ref), None)


def _split(ref):
    kind, _, ident = str(ref).partition(":")
    if kind not in STORE_LABEL or not ident:
        raise ValueError("unknown memory " + str(ref))
    return kind, ident


def update(ref, text=None, category=None):
    """Edit one entry. Returns (True, "") or (False, why). Edited text goes through the same checks as new text: secrets are refused, and a sensitive
    category must be switched on."""
    kind, ident = _split(ref)
    if text is not None:
        text = " ".join(str(text).split())
        if not text:
            return False, "The text is empty."
        if len(text) > MAX_TEXT:
            return False, f"Keep it under {MAX_TEXT} characters."
        why = facts.secret_refusal(text)
        if why:
            return False, why
    if category is not None and category not in EDITABLE_CATEGORIES:
        return False, "Pick one of the ordinary categories."
    if kind == "facts":
        return facts.update(ident, text, category)
    with store.db() as con:
        if kind == "memory":
            con.execute("UPDATE facts SET value=COALESCE(?, value), category=COALESCE(?, category), updated=? WHERE id=?",
                        (text, category, memory._now(), ident))
        elif kind == "people":
            if text is not None:
                m = re.match(r"^(.*?)\s*\(([^)]*)\)\s*$", text)
                name, relation = (m.group(1).strip(), m.group(2).strip()) if m else (text, "")
                con.execute("UPDATE people SET name=?, relation=? WHERE id=?", (name, relation, ident))
        else:
            if text is not None:
                con.execute("UPDATE episodes SET summary=? WHERE id=?", (text, ident))
    return True, ""


def delete(refs):
    """Delete the chosen entries. Returns how many went."""
    gone = 0
    facts_ids = []
    for ref in refs:
        kind, ident = _split(ref)
        if kind == "facts":
            facts_ids.append(ident)
            continue
        with store.db() as con:
            cur = con.execute(f"DELETE FROM {'facts' if kind == 'memory' else kind} WHERE id=?", (ident,))
            gone += cur.rowcount
    if facts_ids:
        gone += facts.delete_many(facts_ids)
    return gone


def clear_all():
    """Forget everything stored about the user: long-term facts, facts, people and conversation summaries. Chats are kept separately."""
    n = len(entries())
    facts.clear()
    with store.db() as con:
        for table in ("facts", "people", "episodes"):
            con.execute(f"DELETE FROM {table}")
    return n
