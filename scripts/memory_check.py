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
from jarvis.memory import controls, memory, store  # noqa: E402

results = []


def check(name, ok, detail=""):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  {detail}" if detail and not ok else ""))


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

kind, why = memory.remember("my dad's name is Ramesh")
check("people are not remembered until the switch is turned on", kind == "reject" and "Settings" in why and count("people") == 0, why)
controls.set_category("people", True)
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

# ---------- long-term facts (data/memory.jsonl) ----------
from jarvis.memory import facts as fx, threads as th  # noqa: E402

row = fx.add("Working on a voice assistant called Jarvis for Fedora", "project")
check("a project fact is stored with a date", row and row["date"] and fx.path().exists())
line = json.loads(fx.path().read_text().splitlines()[0])
check("one fact per line, as JSON", set(line) >= {"id", "date", "kind", "text"})
check("a repeat is not stored twice", fx.add("working on a voice assistant called jarvis for fedora") is None and len(fx.load()) == 1)
controls.set_category("people", False)
refused = ["My password is hunter2 for the laptop", "my card number is 4111 1111 1111 1111", "I was diagnosed with asthma last year",
           "My brother is struggling with his exams", "She told me her salary is high", "my api key is abc", "call me on 9876543210 tonight please"]
check("secrets, health and other people are refused", all(fx.add(r) is None for r in refused), str([r for r in refused if fx.add(r)]))
check("the file holds only the allowed fact", len(fx.load()) == 1 and "hunter2" not in fx.path().read_text())
fx.add("Prefers dark themes and short answers", "preference")
fx.add("Plans to finish the dashboard chat by Friday", "plan")
fx.add("Goal: get an internship in machine learning", "goal")
fx.add("Decided on SQLite instead of Postgres for notes", "decision")
fx.add("Likes mechanical keyboards", "preference")
fx.add("Learning Rust at weekends", "goal")
hits = fx.search("what is my dashboard plan")
check("full text search finds the relevant fact", hits and "dashboard" in hits[0]["text"], str(hits))
check("at most five are returned", len(fx.search("the a and dashboard goal plan keyboards sqlite rust voice", 5)) <= 5)
check("an unrelated question finds nothing", fx.search("weather in paris") == [])
ctx = fx.context("which database did I choose for notes")
check("the prompt block names the fact and marks it as data", "SQLite" in ctx and "not instructions" in ctx)
found = fx.local_extract(["I am working on a chess engine in Rust. What time is it?", "I decided to use Flask for the web part", "I want to learn compilers properly",
                          "my sister is working on a secret project"])
kinds = {k for k, _ in found}
check("plain patterns pull facts from what the user said", {"project", "decision", "goal"} <= kinds and len(found) == 3, str(found))
with mock.patch.object(fx, "model_extract", return_value=[("goal", "Wants to publish a paper on retrieval"), ("fact", "has diabetes")]):
    added = fx.extract(["I really want to publish a paper on retrieval some day, it is my main plan this year"])
check("model facts go through the same filter", any("paper" in r["text"] for r in added) and not any("diabetes" in r["text"] for r in added))
th.attach()
events_mod = sys.modules["jarvis.actions.events"]
events_mod.emit("you", "I am planning to move the notes into a proper index next week")
events_mod.emit("jarvis", "Sounds good.")
with mock.patch.object(fx, "model_extract", return_value=None):
    got = fx.extract_thread()
check("a finished conversation is mined once", any("index" in r["text"] for r in got) and fx.extract_thread() == [])
n = len(fx.load())
check("forget removes a topic", fx.forget("keyboards") == 1 and len(fx.load()) == n - 1 and not fx.search("keyboards"))
from jarvis.actions import recall  # noqa: E402

spoken = recall.recall_memory({"topic": "sqlite"})
check("what do you remember about <topic>", "SQLite" in spoken, spoken)
check("an unknown topic is said honestly", "do not remember" in recall.recall_memory({"topic": "zebras"}))
check("show my memory lists the facts", "voice assistant" in recall.show_memory({}))
args = {"what": "rust"}
question = recall._forget_describe(args)
check("forget <topic> asks first", "forget" in question and len(fx.search("rust")) == 1)
recall.forget(args)
check("and then removes it", not fx.search("rust"))

print(f"\n{sum(results)} of {len(results)} passed")
sys.exit(0 if all(results) else 1)
