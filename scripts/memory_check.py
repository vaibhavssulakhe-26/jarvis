"""Checks the memory store against a scratch database. Run: python scripts/memory_check.py"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-memory-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["USER_PET_NAME"] = "Testy"
os.environ["MEMORY_FILE"] = str(tmp / "old-memory.json")

from jarvis.brain import brain  # noqa: E402
from jarvis.core import config  # noqa: E402
from jarvis.memory import memory, store  # noqa: E402

results = []


def check(name, ok):
    results.append(ok)
    print(("PASS  " if ok else "FAIL  ") + name)


def count(table):
    with store.db() as con:
        return con.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]


store.PATH = tmp / "memory.db"

# old files to migrate
(tmp / "old-memory.json").write_text(json.dumps({"facts": ["User's name is Somebody Else", "I study computer science"]}))
(tmp / "notes").mkdir()
(tmp / "notes" / "dsa.txt").write_text("[2026-11-01 20:00] finish chapter 3\n")
memory.migrate()
facts = memory.top_facts(10)
check("migration keeps normal facts", "I study computer science" in facts)
check("migration drops a stored user name", not any("name" in f.lower() for f in facts))
check("migration imports notes", count("notes") == 1)
check("old files stay untouched", (tmp / "notes" / "dsa.txt").exists() and (tmp / "old-memory.json").exists())

kind, _ = memory.remember("my dad's name is Ramesh")
check("father's name goes to people", kind == "person" and count("people") == 1)
with store.db() as con:
    row = con.execute("SELECT name, relation FROM people").fetchone()
check("person stored with relation", (row["name"], row["relation"]) == ("Ramesh", "dad"))
check("father's name is not a fact", not any("ramesh" in f.lower() for f in memory.top_facts(10)))

before = count("facts")
kind, msg = memory.remember("call me Raju")
check("'call me Y' is rejected", kind == "reject" and count("facts") == before)
check("rejection keeps the pet name", "Testy" in msg)
check("user's name statement rejected", memory.remember("The user's name is Raju", key="name")[0] == "reject")
check("nickname rejected", memory.remember("My nickname is Raj")[0] == "reject")
check("'X is my friend' goes to people", memory.remember("Arjun is my friend")[0] == "person")
check("father with extra detail", memory.remember("my father's name is Suresh and he is a doctor")[0] == "person")
with store.db() as con:
    names = {r["name"] for r in con.execute("SELECT name FROM people")}
check("extra words are not part of the name", "Suresh" in names)

kind, _ = memory.remember("I like biryani")
check("normal fact saved", kind == "fact")

ctx = memory.context("what food do I like")
check("context has relevant fact", "biryani" in ctx)
check("context fixes the pet name", "only as Testy" in ctx)
check("context holds no relative's name", "Ramesh" not in ctx and "Raju" not in ctx)
check("no memory block for chit-chat", "biryani" not in memory.context("hello") and "Remembered" not in memory.context("thanks"))
check("context stays small", len(memory.context("what food do I like")) < 1100)
check("config name unchanged", config.PET_NAME == "Testy")

hit = memory.find_facts("biryani")
check("forget finds the fact", bool(hit) and hit[0][0] == "fact")
memory.delete(hit[0][0], hit[0][1])
check("forget deletes it", not memory.find_facts("biryani"))

# episode summaries after 12 archived turns
with mock.patch.object(brain, "ask", return_value="We talked about study plans."):
    memory.archive_turns([("user" if i % 2 == 0 else "assistant", f"line {i}") for i in range(11)])
    check("no summary before 12 turns", count("episodes") == 0)
    memory.archive_turns([("user", "line 11")])
    for _ in range(30):
        if count("episodes"):
            break
        time.sleep(0.1)
check("summary written after 12 turns", count("episodes") == 1)
check("turns kept after summary", count("turns") == 12)
memory.MAX_TURNS = 5
memory._cap_turns()
check("turn cap removes oldest summarised rows", count("turns") == 5)
with mock.patch.object(brain, "ask", return_value=""):
    memory.archive_turns([("user", "unsummarised a"), ("user", "unsummarised b")])
    memory.summarise_pending()
    memory._cap_turns()
with store.db() as con:
    kept = [r["text"] for r in con.execute("SELECT text FROM turns")]
check("unsummarised turns are never deleted", "unsummarised a" in kept and "unsummarised b" in kept)

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
