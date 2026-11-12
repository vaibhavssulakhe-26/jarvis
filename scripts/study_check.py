"""Checks the study buddy: quizzes, grading, weak topics, lessons, roadmap, daily check-in, week summary. No network.
Run: python scripts/study_check.py"""
import os
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

scratch = Path(tempfile.mkdtemp(prefix="jarvis-study-"))
os.environ["JARVIS_DATA"] = str(scratch)
os.environ["XDG_STATE_HOME"] = str(scratch)
os.environ["XDG_RUNTIME_DIR"] = str(scratch)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import study  # noqa: E402
from jarvis.core import main  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


T = tools.TOOLS
said = []
model = {"reply": ""}


def fake_ask(prompt, max_tokens=0, **kw):
    return model["reply"](prompt) if callable(model["reply"]) else model["reply"]


patches = [mock.patch.object(study.brain, "ask", fake_ask), mock.patch.object(main.voice, "say", lambda t: said.append(str(t)))]
for p in patches:
    p.start()

check("topics are recognised", [study.canon(x) for x in ("arrays", "linked lists", "binary tree", "BFS", "dynamic programming", "DP", "sorting")]
      == ["arrays", "linked lists", "trees", "graphs", "dp", "dp", ""])

# quiz: model path
model["reply"] = "Q: What does BFS use to track nodes?\nA: A queue holds the nodes in visit order."
out = T["quiz_me"]["fn"]({"topic": "graphs"})
check("quiz me asks one question", "BFS" in out and study.waiting(), out)
model["reply"] = "GRADE: CORRECT - Yes, a queue gives level order."
reply = study.take("it uses a queue")
check("a right answer is graded and tracked", reply.startswith("Correct.") and not study.waiting(), reply)
data = study.load()
check("the score is saved in study.json", data["topics"]["graphs"] == {"asked": 1, "score": 1.0, "last": date.today().isoformat()}
      and (scratch / "study.json").exists(), str(data))

# wrong answer reveals the reference, and the topic becomes weak
model["reply"] = lambda prompt: "Q: What is a base case?\nA: The input that stops recursion." if prompt.startswith("Write") else "GRADE: WRONG - A base case ends the recursion."
T["quiz_me"]["fn"]({"topic": "dp"})
reply = study.take("no idea what that is maybe sorting")
check("a wrong answer gives the real answer", reply.startswith("Not quite.") and "stops recursion" in reply, reply)
check("weak topics lists dp", study.weak_topics() == ["dp"])
check("the progress tool names the weak topic", "dp" in T["study_progress"]["fn"]({}))
model["reply"] = "Q: What is memoization?\nA: Caching results of subproblems."
check("quiz me with no topic picks the weakest", T["quiz_me"]["fn"]({"topic": ""}).startswith("Dp question"))
study.cancel()
model["reply"] = ""
out = T["quiz_me"]["fn"]({"topic": ""})
check("with no model the built-in bank is used on the weakest topic", "dp" in out.lower() and study.waiting(), out)

# local grading when the model is down
model["reply"] = ""
study.cancel()
T["quiz_me"]["fn"]({"topic": "trees"})
question = study._session["question"]
reply = study.take(study._session["reference"])
check("with no model the keyword grade still works", reply.startswith("Correct."), reply)
T["quiz_me"]["fn"]({"topic": "trees"})
reply = study.take("banana")
check("an unrelated answer is wrong offline", reply.startswith("Not quite.") and "answer is" in reply, reply)

# controls
T["quiz_me"]["fn"]({"topic": "arrays"})
check("a command is not graded as an answer", study.take("open firefox") is None and study.waiting())
reply = study.take("I don't know")
check("don't know reveals the answer and counts as wrong", "answer is" in reply and not study.waiting(), reply)
T["quiz_me"]["fn"]({"topic": "arrays"})
check("stop ends the quiz", study.take("stop") == "Okay, stopped." and not study.waiting())
check("nothing happens when no question is open", study.take("it uses a queue") is None)
T["quiz_me"]["fn"]({"topic": "arrays"})
study._session["until"] = time.time() - 1
check("an old question expires", study.take("a queue") is None)
try:
    T["quiz_me"]["fn"]({"topic": "quantum physics"})
    check("an unknown topic is refused", False)
except tools.ToolError:
    check("an unknown topic is refused", True)

# repeated questions are avoided
model["reply"] = ""
seen = set()
study.cancel()
study._session.clear()
for _ in range(3):
    T["quiz_me"]["fn"]({"topic": "graphs"})
    seen.add(study._session["question"])
    study.cancel()
check("the same topic gives different built-in questions", len(seen) >= 2, str(seen))

# teach me
model["reply"] = ("Recursion is when a function calls itself. It needs a base case to stop. Each call has its own stack frame. "
                  "A fourth sentence.\nQ: What is a base case?\nA: The condition where recursion stops.")
out = T["teach_me"]["fn"]({"topic": "recursion"})
check("teach me gives three sentences then one question", out.count(".") >= 3 and "fourth" not in out and out.endswith("What is a base case?"), out)
check("and waits for the answer", study.waiting() and study._session["question"] == "What is a base case?")
model["reply"] = "GRADE: CORRECT - Right."
check("the answer to the lesson question is graded", study.take("where it stops").startswith("Correct."))

# roadmap
(scratch / "roadmap.md").write_text("# Plan\n\n- [x] Python basics\n- [ ] Arrays and strings\n- [ ] Linked lists\n2. Trees\n")
check("roadmap next gives the first open item", T["roadmap_next"]["fn"]({}).startswith("Next on your roadmap: Arrays and strings."))
out = T["roadmap_done"]["fn"]({"item": "arrays"})
check("mark done ticks the item and names the next", "Marked Arrays and strings done" in out and "Next is Linked lists" in out, out)
check("the file is updated and the rest is unchanged", "- [x] Arrays and strings" in (scratch / "roadmap.md").read_text()
      and "# Plan" in (scratch / "roadmap.md").read_text())
check("a misheard item still matches", "Linked lists" in T["roadmap_done"]["fn"]({"item": "linked list"}))
check("plain numbered items are items", "Trees" in T["roadmap_next"]["fn"]({}))
check("done twice says so", "already done" in T["roadmap_done"]["fn"]({"item": "python basics"}))
try:
    T["roadmap_done"]["fn"]({"item": "kubernetes"})
    check("an unknown item is refused", False)
except tools.ToolError:
    check("an unknown item is refused", True)
T["roadmap_done"]["fn"]({"item": "trees"})
check("a finished roadmap says so", "done" in T["roadmap_next"]["fn"]({}))
(scratch / "roadmap.md").unlink()
try:
    T["roadmap_next"]["fn"]({})
    check("a missing roadmap file is explained", False)
except tools.ToolError as e:
    check("a missing roadmap file is explained", "roadmap" in str(e))

# parsing for the check-in
check("sleep times parse", [study.parse_sleep(x) for x in ("11:30 pm", "eleven thirty pm", "midnight", "1 am", "around 23:15", "11 30 p.m.")]
      == ["23:30", "23:30", "00:00", "01:00", "23:15", "23:30"], str([study.parse_sleep(x) for x in ("11:30 pm", "eleven thirty pm", "midnight", "1 am", "around 23:15", "11 30 p.m.")]))
check("yes and no parse", [study.parse_yes_no(x) for x in ("yes", "yeah I did", "no", "nope not today", "maybe")] == [True, True, False, False, None])
check("minutes parse", [study.parse_minutes(x) for x in ("90 minutes", "an hour", "two hours", "1.5 hours", "45", "none", "half an hour")] == [90, 60, 120, 90, 45, 0, 30],
      str([study.parse_minutes(x) for x in ("90 minutes", "an hour", "two hours", "1.5 hours", "45", "none", "half an hour")]))
check("a one-line check-in is understood", study.checkin_from("slept at 11:30 pm, walked, studied 90 minutes") == {"sleep": "23:30", "walk": True, "study_min": 90},
      str(study.checkin_from("slept at 11:30 pm, walked, studied 90 minutes")))

# log today, asked one by one
out = T["log_today"]["fn"]({"text": ""})
check("log today asks for sleep first", "sleep" in out.lower() and study.waiting(), out)
check("an unclear answer repeats the question", "sleep" in study.take("hmm").lower())
check("then asks about the walk", "walk" in study.take("around 11 30 pm").lower())
check("then about study", "minutes" in study.take("yes").lower())
out = study.take("two hours")
d = study.load()["days"][date.today().isoformat()]
check("the entry is saved", d["sleep"] == "23:30" and d["walk"] is True and d["study_min"] == 120 and "Logged" in out, f"{d} {out}")
out = T["log_today"]["fn"]({"text": "slept at midnight, no walk, studied 30 minutes"})
check("everything in one sentence is logged without questions", not study.waiting() and "Logged" in out, out)
check("study minutes keep the larger value for the day", study.load()["days"][date.today().isoformat()]["study_min"] == 120)

# week summary and streak
data = study.load()
for i in (1, 2, 3):
    data["days"][(date.today() - timedelta(days=i)).isoformat()] = {"sleep": "23:00", "walk": i != 2, "study_min": 60}
study.save(data)
out = T["week_summary"]["fn"]({})
check("week summary reports minutes, walks and sleep", "minutes" in out and "walked" in out and "around" in out and "streak is 4" in out, out)
check("the streak counts study days in a row", study.streak() == 4)
study.add_minutes(25)
check("add_minutes credits today", study.load()["days"][date.today().isoformat()]["study_min"] == 145)
(scratch / "study.json").write_text("not json")
check("a damaged study file starts fresh", study.load() == {"topics": {}, "days": {}})
check("an empty week says so", "nothing logged" in T["week_summary"]["fn"]({}))

# routing: direct commands, no brain
ran = []
cases = (("quiz me on trees", "quiz_me", {"topic": "trees"}), ("quiz me", "quiz_me", {"topic": ""}), ("teach me about recursion", "teach_me", {"topic": "recursion"}),
         ("what's next on my roadmap", "roadmap_next", {}), ("mark arrays done", "roadmap_done", {"item": "arrays"}), ("log today", "log_today", {"text": ""}),
         ("how was my week", "week_summary", {}), ("what are my weak topics", "study_progress", {}))
for phrase, name, args in cases:
    with mock.patch.object(main, "run_tool", lambda a, ar, s: ran.append((a, ar))), mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")):
        main.direct(phrase)
    check(f"{phrase!r} -> {name}", ran and ran[-1] == (name, args), str(ran[-1:]))

# end to end through the real handler: the next sentence is the answer
del said[:]
model["reply"] = lambda prompt: "Q: What is a stack?\nA: Last in, first out." if prompt.startswith("Write") else "GRADE: CORRECT - Yes."
with mock.patch.object(main.brain, "think", side_effect=AssertionError("brain")), mock.patch.object(main.brain, "chat", side_effect=AssertionError("brain")):
    keep = main._handle("quiz me on arrays")
    check("handle keeps listening for the answer", keep is True and any("stack" in s for s in said), str(said))
    keep = main._handle("last in first out")
    check("the spoken answer is graded in the handler", any(s.startswith("Correct.") for s in said) and keep is False, str(said))
    main._handle("quiz me on arrays")
    main._handle("stop")
    check("stop ends a quiz in the handler", not study.waiting())
for p in patches:
    p.stop()
sys.exit(1 if bad else 0)
