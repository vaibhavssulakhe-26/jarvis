"""Study buddy: DSA quizzes, short lessons, the roadmap file, and the daily check-in."""
import difflib
import os
import random
import re
import time
from datetime import date, timedelta

from ..brain import brain
from ..core import config, jsonfile
from .tools import ToolError, tool

TOPICS = {
    "arrays": ("array", "arrays", "strings", "two pointers", "sliding window"),
    "linked lists": ("linked list", "linked lists", "list node", "lists"),
    "trees": ("tree", "trees", "bst", "binary tree", "binary search tree", "heap"),
    "graphs": ("graph", "graphs", "bfs", "dfs", "dijkstra"),
    "dp": ("dp", "dynamic programming"),
}
BANK = {
    "arrays": [("What is the time complexity of reading an array element by its index?", "constant time, O(1), because the address is computed directly"),
               ("What does the two pointer technique do on a sorted array?", "two indexes move toward each other to find a pair in linear time"),
               ("Why is inserting in the middle of an array slow?", "the elements after it must shift, which takes linear time")],
    "linked lists": [("How do you detect a cycle in a linked list?", "use a slow and a fast pointer, they meet if there is a cycle"),
                     ("What is the cost of inserting at the head of a singly linked list?", "constant time, O(1), only the head pointer changes"),
                     ("How do you reverse a singly linked list?", "walk the list and flip each next pointer using previous, current and next")],
    "trees": [("What does an inorder traversal of a binary search tree give you?", "the values in sorted order"),
              ("What is the height of a balanced binary tree with n nodes?", "about log n, O(log n)"),
              ("Which traversal uses a queue?", "level order, which is breadth first search")],
    "graphs": [("Which data structure does breadth first search use?", "a queue"),
               ("Why does Dijkstra fail with negative edge weights?", "it assumes a finalised node has the shortest path, which negative edges can break"),
               ("How do you store a sparse graph?", "an adjacency list")],
    "dp": [("What two properties make a problem suitable for dynamic programming?", "overlapping subproblems and optimal substructure"),
           ("What is the difference between memoization and tabulation?", "memoization is top down with a cache, tabulation fills a table bottom up"),
           ("What is the time complexity of the Fibonacci number with dynamic programming?", "linear, O(n)")],
}
SESSION_SECONDS = 300
WEAK_BELOW = 0.6
_session = {}
_last = {"topic": ""}


# ---------- storage ----------
def path():
    return config.DATA / "study.json"


def load():
    data = jsonfile.read(path(), {}, dict)
    data.setdefault("topics", {})
    data.setdefault("days", {})
    return data


def save(data):
    jsonfile.write(path(), data, indent=1)


def day(data, when=None):
    return data["days"].setdefault((when or date.today()).isoformat(), {})


def add_minutes(minutes):
    """Credit study time to today; the focus timer calls this when a session ends."""
    data = load()
    d = day(data)
    d["study_min"] = int(d.get("study_min", 0)) + int(minutes)
    save(data)


# ---------- topics ----------
def canon(text):
    t = re.sub(r"[^a-z ]", " ", str(text).lower())
    t = " ".join(t.split())
    if not t:
        return ""
    for name, words in TOPICS.items():
        if t == name or t in words:
            return name
    for name, words in TOPICS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", t) for w in words):
            return name
    return ""


def record(topic, score):
    data = load()
    row = data["topics"].setdefault(topic, {"asked": 0, "score": 0.0})
    row["asked"] += 1
    row["score"] += score
    row["last"] = date.today().isoformat()
    d = day(data)
    d["quizzed"] = int(d.get("quizzed", 0)) + 1
    save(data)


def accuracy(row):
    return row["score"] / row["asked"] if row.get("asked") else 1.0


def weak_topics(data=None):
    data = data or load()
    rows = [(accuracy(r), t) for t, r in data["topics"].items() if r.get("asked")]
    return [t for a, t in sorted(rows) if a < WEAK_BELOW]


def pick_topic():
    data = load()
    weak = weak_topics(data)
    if weak:
        return weak[0]
    fresh = [t for t in TOPICS if t not in data["topics"]]
    return random.choice(fresh or list(TOPICS))


# ---------- questions ----------
def parse_qa(text):
    m = re.search(r"Q:\s*(.+?)\s*\n+\s*A:\s*(.+)", str(text), re.S)
    if not m:
        return None
    q, a = " ".join(m.group(1).split()), " ".join(m.group(2).split())
    return (q, a) if q and a else None


def make_question(topic):
    asked = _session.get("seen", [])[-3:]
    avoid = (" Do not repeat: " + " | ".join(a[:60] for a in asked)) if asked else ""
    reply = brain.ask(f"Write one short quiz question on {topic} for a student learning data structures and algorithms. "
                      "It must be answerable in one or two spoken sentences. Reply exactly as:\nQ: <question>\n"
                      f"A: <reference answer in one sentence>{avoid}", 120)
    qa = parse_qa(reply)
    if qa:
        return qa
    options = [q for q in BANK.get(topic, sum(BANK.values(), [])) if q[0] not in asked]
    return random.choice(options or BANK.get(topic) or sum(BANK.values(), []))


def keywords(text):
    return {w for w in re.findall(r"[a-z0-9]{4,}", str(text).lower())} - {"that", "this", "with", "from", "because", "which", "their", "there"}


def local_grade(reference, answer):
    ref = keywords(reference)
    if not ref:
        return "partial", ""
    got = len(ref & keywords(answer)) / len(ref)
    return ("correct" if got >= 0.5 else "partial" if got >= 0.25 else "wrong"), ""


def grade(question, reference, answer):
    """(verdict, feedback). The model grades when it can; otherwise keyword overlap against the reference."""
    reply = brain.ask(f"Question: {question}\nReference answer: {reference}\nStudent said: {answer[:300]}\n"
                      "Grade the student as CORRECT, PARTIAL or WRONG, then give one short sentence of feedback. "
                      "Reply exactly as: GRADE: <word> - <feedback>", 80)
    m = re.search(r"GRADE:\s*(correct|partial|wrong)\W*(.*)", str(reply), re.I | re.S)
    if m:
        return m.group(1).lower(), " ".join(m.group(2).split())
    return local_grade(reference, answer)[0], ""


SCORE = {"correct": 1.0, "partial": 0.5, "wrong": 0.0}
OPENERS = {"correct": "Correct.", "partial": "Partly right.", "wrong": "Not quite."}


def ask_next(topic):
    q, a = make_question(topic)
    _session.update(kind="quiz", topic=topic, question=q, reference=a, until=time.time() + SESSION_SECONDS,
                    seen=(_session.get("seen", []) + [q])[-6:])
    _last["topic"] = topic
    return q


# ---------- check-in parsing ----------
NUM = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten eleven twelve".split())}
NUM.update({"fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "fifty": 50, "sixty": 60, "ninety": 90})


def parse_sleep(text):
    """'11:30 pm', 'eleven thirty', 'midnight', 'around 1 am' -> 'HH:MM', or None."""
    t = str(text).lower().replace(".", "")
    if "midnight" in t:
        return "00:00"
    for word, n in sorted(NUM.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{word}\b", str(n), t)
    m = re.search(r"\b(\d{1,2})(?:[: ]?(\d{2}))?\s*(am|pm|a m|p m)?\b", t)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    ap = (m.group(3) or "").replace(" ", "")
    if ap:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ap == "pm" else 0)
    elif h > 23:
        return None
    return f"{h:02d}:{mi:02d}" if mi < 60 else None


def parse_yes_no(text):
    words = re.findall(r"[a-z]+", str(text).lower())
    if not words:
        return None
    if set(words[:4]) & {"no", "nope", "nah", "didn", "didnt", "not", "never"}:
        return False
    if set(words[:4]) & {"yes", "yeah", "yep", "yup", "sure", "did", "went", "walked", "took"}:
        return True
    return None


def parse_minutes(text):
    t = str(text).lower()
    if re.search(r"\bno(?:thing)?\b|\bnone\b|\bzero\b", t) and not re.search(r"\d", t):
        return 0
    total, found = 0, False
    for m in re.finditer(r"(\d+(?:\.\d+)?|an?|half an?|one|two|three|four|five|six|seven|eight)\s*(hours?|hrs?|minutes?|mins?)", t):
        raw, unit = m.group(1), m.group(2)
        n = 0.5 if raw.startswith("half") else float(raw) if raw[0].isdigit() else 1 if raw in ("a", "an") else NUM.get(raw, 0)
        total += n * (60 if unit.startswith("h") else 1)
        found = True
    if found:
        return int(total)
    m = re.fullmatch(r"\D*(\d{1,3})\D*", t)
    return int(m.group(1)) if m else None


CHECKIN = (("sleep", "What time did you go to sleep?", parse_sleep),
           ("walk", "Did you go for a walk today? Yes or no.", parse_yes_no),
           ("study_min", "How many minutes did you study?", parse_minutes))


def checkin_from(text):
    """Pull whatever the sentence already says: 'slept at 11:30, walked, studied 90 minutes'."""
    t = str(text)
    out = {}
    m = re.search(r"(?:slept|sleep|bed)\D{0,12}(?:at|around|by)?\s*([\d: ]+\s*(?:am|pm|a m|p m)?|midnight)", t, re.I)
    if m:
        out["sleep"] = parse_sleep(m.group(1))
    if re.search(r"\b(?:no walk|didn'?t walk|did not walk|skipped (?:the )?walk)\b", t, re.I):
        out["walk"] = False
    elif re.search(r"\b(?:walked|went for a walk|walk (?:yes|done)|took a walk)\b", t, re.I):
        out["walk"] = True
    m = re.search(r"stud(?:y|ied)\D{0,12}(\d+(?:\.\d+)?|an?|half an?)\s*(hours?|hrs?|minutes?|mins?)", t, re.I)
    if m:
        out["study_min"] = parse_minutes(m.group(1) + " " + m.group(2))
    return {k: v for k, v in out.items() if v is not None}


def save_checkin(values):
    data = load()
    d = day(data)
    for key, value in values.items():
        if key == "study_min":
            d[key] = max(int(d.get(key, 0)), int(value))
        else:
            d[key] = value
    save(data)
    return d


def next_missing(values):
    return next((k for k, _, _ in CHECKIN if k not in values), None)


def checkin_line(values):
    bits = []
    if values.get("sleep"):
        bits.append("slept at " + values["sleep"])
    if "walk" in values:
        bits.append("walked" if values["walk"] else "no walk")
    if "study_min" in values:
        bits.append(f"studied {values['study_min']} minutes")
    return "Logged: " + ", ".join(bits) + "."


# ---------- the open question ----------
def waiting():
    return bool(_session) and time.time() < _session.get("until", 0)


def cancel():
    _session.pop("kind", None)
    _session.pop("until", None)


CONTROL_STOP = re.compile(r"^(?:stop|cancel|end|quit|exit|enough|never ?mind|that'?s enough)(?: the)?(?: quiz| lesson| check-?in)?$", re.I)
CONTROL_SKIP = re.compile(r"^(?:i )?(?:don'?t know|no idea|skip(?: it| this| this one| question)?|pass|give up|tell me)$", re.I)
CONTROL_NEXT = re.compile(r"^(?:next|another|next question|another question|one more)$", re.I)
COMMANDISH = re.compile(r"^(?:open|play|remind|set|volume|mute|unmute|what(?:'s| is) the (?:time|date)|screenshot|lock|close|start focus|stop focus|good morning)\b", re.I)


def take(text):
    """Handle the sentence if a quiz question or check-in question is open. Returns the reply, or None when it is not for us."""
    if not waiting():
        _session.clear()
        return None
    t = " ".join(str(text).strip().rstrip(".!?").split())
    if not t:
        return None
    if CONTROL_STOP.match(t):
        cancel()
        return "Okay, stopped."
    if _session["kind"] == "checkin":
        return _take_checkin(t)
    if COMMANDISH.match(t):
        return None
    if CONTROL_NEXT.match(t):
        return ask_next(_session["topic"])
    if CONTROL_SKIP.match(t):
        reference = _session["reference"]
        record(_session["topic"], 0.0)
        cancel()
        return f"No problem. The answer is: {reference}. Say next question when you are ready."
    verdict, feedback = grade(_session["question"], _session["reference"], t)
    record(_session["topic"], SCORE[verdict])
    reference = _session["reference"]
    cancel()
    tail = "" if verdict == "correct" else f" The answer is: {reference}."
    return f"{OPENERS[verdict]} {feedback}{tail} Say next question for another one.".replace("  ", " ")


def _take_checkin(t):
    key = _session["missing"]
    parse = {k: p for k, _, p in CHECKIN}[key]
    value = parse(t)
    if value is None:
        return dict((k, q) for k, q, _ in CHECKIN)[key]
    _session["values"][key] = value
    missing = next_missing(_session["values"])
    if missing:
        _session["missing"] = missing
        _session["until"] = time.time() + SESSION_SECONDS
        return dict((k, q) for k, q, _ in CHECKIN)[missing]
    values = _session["values"]
    cancel()
    save_checkin(values)
    return checkin_line(values)


# ---------- tools ----------
@tool("quiz_me", 'args {"topic": "arrays, linked lists, trees, graphs or dp; empty picks your weakest"} - ask one DSA quiz question and grade the spoken answer; for "quiz me on trees"')
def quiz_me(args):
    raw = str(args.get("topic") or "").strip()
    topic = canon(raw) if raw else ""
    if raw and not topic:
        raise ToolError("I can quiz you on arrays, linked lists, trees, graphs or dynamic programming.")
    topic = topic or pick_topic()
    if _session.get("topic") != topic:
        _session.pop("seen", None)
    question = ask_next(topic)
    return f"{topic.title() if topic == 'dp' else topic.capitalize()} question. {question}"


@tool("teach_me", 'args {"topic": "<what to learn>"} - explain a topic in three sentences, then ask one question; for "teach me about recursion"')
def teach_me(args):
    topic = " ".join(str(args.get("topic") or "").split())[:60]
    if not topic:
        raise ToolError("What should I teach you?")
    reply = brain.ask(f"Explain {topic} to a student in exactly 3 short spoken sentences, no lists. Then add two lines: "
                      "Q: <one question that checks understanding>\nA: <the answer in one sentence>", 220, cache=True)
    qa = parse_qa(reply)
    lesson = re.split(r"\n\s*Q:", str(reply))[0].strip()
    lesson = " ".join(lesson.split())
    if not lesson:
        raise ToolError("I could not put a lesson together right now. Try again in a minute.")
    sentences = re.split(r"(?<=[.!?])\s+", lesson)
    lesson = " ".join(sentences[:3])
    if not qa:
        return lesson
    key = canon(topic) or topic.lower()
    _session.update(kind="quiz", topic=key, question=qa[0], reference=qa[1], until=time.time() + SESSION_SECONDS)
    _last["topic"] = key
    return f"{lesson} Question: {qa[0]}"


@tool("study_progress", "args {} - say which DSA topics are weak, from the quiz history; for \"what are my weak topics\"")
def study_progress(args):
    data = load()
    if not data["topics"]:
        return "You have not done any quizzes yet. Say quiz me on arrays to start."
    weak = weak_topics(data)
    best = max(data["topics"], key=lambda t: accuracy(data["topics"][t]))
    if not weak:
        return f"No weak topics right now. Your strongest is {best}."
    row = data["topics"][weak[0]]
    return f"Your weakest topic is {weak[0]}, {round(accuracy(row) * 100)} percent over {row['asked']} questions." + \
        (f" Also work on {', '.join(weak[1:3])}." if len(weak) > 1 else "")


# ---------- roadmap ----------
ITEM = re.compile(r"^(\s*)(?:[-*]|\d+[.)])\s*(?:\[([ xX])\]\s*)?(.+?)\s*$")


def roadmap_path():
    return config.DATA / "roadmap.md"


def roadmap_items():
    """[(line index, done, text)] from data/roadmap.md; headings and prose are not items."""
    try:
        lines = roadmap_path().read_text().splitlines()
    except OSError:
        return None, []
    items = []
    for i, line in enumerate(lines):
        m = ITEM.match(line)
        if m:
            items.append((i, (m.group(2) or " ").lower() == "x", m.group(3)))
    return lines, items


def next_item():
    _, items = roadmap_items()
    return next((text for _, done, text in items if not done), None)


@tool("roadmap_next", 'args {} - say the next unfinished item in the roadmap file; for "what\'s next on my roadmap"')
def roadmap_next(args):
    lines, items = roadmap_items()
    if lines is None:
        raise ToolError("I do not see a roadmap yet. Put one in data slash roadmap dot m d, one item per line.")
    open_items = [t for _, done, t in items if not done]
    if not items:
        raise ToolError("Your roadmap file has no items yet.")
    if not open_items:
        return "Your whole roadmap is done. Nice work."
    more = f" {len(open_items) - 1} more after that." if len(open_items) > 1 else ""
    return f"Next on your roadmap: {open_items[0]}.{more}"


@tool("roadmap_done", 'args {"item": "<words from the item>"} - mark a roadmap item done; for "mark arrays done"')
def roadmap_done(args):
    want = str(args.get("item") or "").lower().strip()
    lines, items = roadmap_items()
    if lines is None:
        raise ToolError("I do not see a roadmap file yet.")
    if not want:
        raise ToolError("Which item should I mark done?")
    texts = [t.lower() for _, _, t in items]
    pick = None
    for n, text in enumerate(texts):
        if want == text or (want in text and not items[n][1]):
            pick = n
            break
    if pick is None:
        close = difflib.get_close_matches(want, texts, 1, 0.6)
        pick = texts.index(close[0]) if close else None
    if pick is None:
        raise ToolError(f"I could not find {want} in your roadmap.")
    index, done, text = items[pick]
    if done:
        return f"{text} is already done."
    m = ITEM.match(lines[index])
    lines[index] = f"{m.group(1)}- [x] {text}"
    tmp = roadmap_path().with_name("roadmap.md.tmp")
    tmp.write_text("\n".join(lines) + "\n")
    os.replace(tmp, roadmap_path())
    after = next_item()
    return f"Marked {text} done." + (f" Next is {after}." if after else " That was the last one.")


# ---------- daily check-in ----------
@tool("log_today", 'args {"text": "<what the user said after log today, if anything>"} - record sleep time, a walk and study minutes for today; asks for what is missing')
def log_today(args):
    values = checkin_from(args.get("text") or "")
    missing = next_missing(values)
    if not missing:
        save_checkin(values)
        return checkin_line(values)
    _session.update(kind="checkin", values=values, missing=missing, until=time.time() + SESSION_SECONDS)
    return dict((k, q) for k, q, _ in CHECKIN)[missing]


def streak(data=None):
    """Days in a row, up to today (or yesterday while today is still empty), with study minutes or a quiz."""
    data = data or load()
    count, d = 0, date.today()
    active = lambda x: (data["days"].get(x.isoformat()) or {}).get("study_min", 0) or (data["days"].get(x.isoformat()) or {}).get("quizzed", 0)
    if not active(d):
        d -= timedelta(days=1)
    while active(d):
        count += 1
        d -= timedelta(days=1)
    return count


def week(data=None):
    data = data or load()
    return [(date.today() - timedelta(days=i), data["days"].get((date.today() - timedelta(days=i)).isoformat()) or {}) for i in range(7)]


@tool("week_summary", 'args {} - a short summary of the last seven days of sleep, walks and study; for "how was my week"')
def week_summary(args):
    data = load()
    rows = [r for _, r in week(data) if r]
    if not rows:
        return "I have nothing logged this week. Say log today to start."
    walks = sum(1 for r in rows if r.get("walk"))
    logged_walk = sum(1 for r in rows if "walk" in r)
    minutes = sum(int(r.get("study_min", 0)) for r in rows)
    sleeps = [int(r["sleep"][:2]) * 60 + int(r["sleep"][3:]) for r in rows if r.get("sleep")]
    parts = [f"You studied {minutes} minutes over {sum(1 for r in rows if r.get('study_min'))} days"]
    if logged_walk:
        parts.append(f"walked {walks} of {logged_walk} days")
    if sleeps:
        adj = [m + 1440 if m < 12 * 60 else m for m in sleeps]
        avg = int(sum(adj) / len(adj)) % 1440
        parts.append(f"went to sleep around {avg // 60:02d}:{avg % 60:02d} on average")
    line = ", ".join(parts) + "."
    s = streak(data)
    if s > 1:
        line += f" Your study streak is {s} days."
    weak = weak_topics(data)
    if weak:
        line += f" Weakest topic: {weak[0]}."
    return line
