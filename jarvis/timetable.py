"""The class timetable and the deadline list, two plain files you can edit by hand.

data/timetable.md   one class per line:  - Mon 09:00-10:00 | Data Structures | Room 204
data/deadlines.md   one deadline per line:  - 2026-11-20 | Submit the DSA assignment
Lines that do not match are ignored, so comments and headings are fine."""
import re
from datetime import date, datetime, timedelta

from .core import config

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
FULL = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december")
CLASS_LINE = re.compile(r"^\s*[-*]\s*([A-Za-z]{3,9})\s+(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})\s*\|\s*([^|]+?)\s*(?:\|\s*(.*?))?\s*$")
DEADLINE_LINE = re.compile(r"^\s*[-*]\s*(\d{4}-\d{2}-\d{2})\s*\|\s*(.+?)\s*$")
HEAD_CLASSES = "# Timetable\n\nOne class per line: `- Mon 09:00-10:00 | Subject | Room`. Edit this file freely.\n\n"
HEAD_DEADLINES = "# Deadlines\n\nOne per line: `- 2026-11-20 | what is due`. Edit this file freely.\n\n"


def timetable_path():
    return config.DATA / "timetable.md"


def deadlines_path():
    return config.DATA / "deadlines.md"


def weekday_of(word):
    word = str(word).lower().strip(".,")
    for i, (short, full) in enumerate(zip(DAYS, FULL)):
        if word in (short, full) or (len(word) >= 3 and full.startswith(word)):
            return i
    return None


def _clock(text):
    h, m = (int(x) for x in text.split(":"))
    return (h, m) if h < 24 and m < 60 else None


def classes():
    """[{day, start, end, subject, room}] from data/timetable.md, sorted by day then start."""
    try:
        lines = timetable_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = CLASS_LINE.match(line)
        day = weekday_of(m.group(1)) if m else None
        if day is None or _clock(m.group(2)) is None or _clock(m.group(3)) is None:
            continue
        out.append({"day": day, "start": "%02d:%02d" % _clock(m.group(2)), "end": "%02d:%02d" % _clock(m.group(3)),
                    "subject": m.group(4), "room": (m.group(5) or "").strip()})
    return sorted(out, key=lambda c: (c["day"], c["start"]))


def classes_on(day):
    return [c for c in classes() if c["day"] == day.weekday()]


def say_class(c, with_day=False):
    return (f"{FULL[c['day']].title()} " if with_day else "") + f"{c['start']} {c['subject']}" + (f", {c['room']}" if c["room"] else "")


def next_class(now=None):
    """(class, date) of the next class that has not started, looking a week ahead, or None."""
    now = now or datetime.now()
    for ahead in range(8):
        day = now.date() + timedelta(days=ahead)
        for c in classes_on(day):
            if ahead or c["start"] > now.strftime("%H:%M"):
                return c, day
    return None


def add_class(day, start, end, subject, room=""):
    subject = re.sub(r"[|\n]", " ", subject).strip()[:50]
    room = re.sub(r"[|\n]", " ", room).strip()[:30]
    if not subject:
        raise ValueError("What is the class called?")
    if start >= end:
        raise ValueError("The class has to end after it starts.")
    path = timetable_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEAD_CLASSES, encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {DAYS[day].title()} {start}-{end} | {subject}" + (f" | {room}" if room else "") + "\n")
    return subject


def deadlines():
    """[{date, item}] sorted by date."""
    try:
        lines = deadlines_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = DEADLINE_LINE.match(line)
        if m:
            try:
                out.append({"date": date.fromisoformat(m.group(1)), "item": m.group(2)})
            except ValueError:
                continue
    return sorted(out, key=lambda d: d["date"])


def add_deadline(item, when):
    item = re.sub(r"[|\n]", " ", item).strip(" .")[:100]
    if not item:
        raise ValueError("What is due?")
    path = deadlines_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(HEAD_DEADLINES, encoding="utf-8")
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {when.isoformat()} | {item}\n")
    return item


def countdown(when, today=None):
    n = (when - (today or date.today())).days
    if n == 0:
        return "today"
    if n == 1:
        return "tomorrow"
    return f"in {n} days" if n > 0 else f"{-n} day{'s' if n < -1 else ''} ago"


def due_within(days, today=None):
    """Deadlines from today up to `days` days ahead, plus anything overdue by less than a week."""
    today = today or date.today()
    return [d for d in deadlines() if today - timedelta(days=7) <= d["date"] <= today + timedelta(days=days)]


def say_deadline(d, today=None):
    return f"{d['item']}, {countdown(d['date'], today)}"


# ---------- parsing spoken text ----------
def parse_date(text, today=None):
    """A date from words such as 'friday', 'next monday', 'tomorrow', '20 november', 'november 20th', '20/11', '2026-11-20' or 'in 3 days'. None if unclear."""
    today = today or date.today()
    t = " ".join(str(text).lower().replace(",", " ").split())
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if "day after tomorrow" in t:
        return today + timedelta(days=2)
    if re.search(r"\btomorrow\b", t):
        return today + timedelta(days=1)
    if re.search(r"\btoday\b|\btonight\b", t):
        return today
    m = re.search(r"\bin (\d{1,3}) (day|week)s?\b", t)
    if m:
        return today + timedelta(days=int(m.group(1)) * (7 if m.group(2) == "week" else 1))
    month = "|".join(MONTHS + tuple(x[:3] for x in MONTHS))
    for pattern, order in ((rf"\b(\d{{1,2}})(?:st|nd|rd|th)?(?: of)? ({month})(?:\s+(\d{{4}}))?\b", "dm"),
                           (rf"\b({month})\.? (\d{{1,2}})(?:st|nd|rd|th)?(?:\s+(\d{{4}}))?\b", "md")):
        m = re.search(pattern, t)
        if m:
            d, mo = (m.group(1), m.group(2)) if order == "dm" else (m.group(2), m.group(1))
            mo = next(i for i, name in enumerate(MONTHS, 1) if name.startswith(mo[:3]))
            return _resolve(today, int(d), mo, int(m.group(3)) if m.group(3) else None)
    m = re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b", t)
    if m:
        year = int(m.group(3)) + (2000 if m.group(3) and len(m.group(3)) == 2 else 0) if m.group(3) else None
        return _resolve(today, int(m.group(1)), int(m.group(2)), year)
    for word in re.findall(r"[a-z]+", t):
        day = weekday_of(word) if len(word) >= 3 else None
        if day is not None:
            ahead = (day - today.weekday()) % 7
            if ahead == 0 and re.search(r"\bnext\b", t):
                ahead = 7
            return today + timedelta(days=ahead)
    return None


def _resolve(today, day, month, year):
    try:
        if year:
            return date(year, month, day)
        found = date(today.year, month, day)
        return found if found >= today else date(today.year + 1, month, day)
    except ValueError:
        return None


TIME_RANGE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s*(?:to|-|until|till)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", re.I)


def parse_range(text):
    """(start, end, text without the range) as 'HH:MM' strings from '9 to 10', '2 pm to 3:30 pm' or '09:00-10:00', or None."""
    m = TIME_RANGE.search(text)
    if not m:
        return None
    h1, m1, a1, h2, m2, a2 = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower(), int(m.group(4)), int(m.group(5) or 0), (m.group(6) or "").lower()
    a2 = a2 or a1
    a1 = a1 or a2
    if h1 > 23 or h2 > 23 or m1 > 59 or m2 > 59:
        return None
    for_end = [h2]
    if a1 or a2:
        h1 = h1 % 12 + (12 if a1 == "pm" else 0)
        h2 = h2 % 12 + (12 if a2 == "pm" else 0)
    elif 1 <= h1 < 7 and not m.group(1).startswith("0"):
        h1 += 12
        h2 = h2 + 12 if h2 < 12 else h2
    if (h2, m2) <= (h1, m1) and for_end[0] < 12:
        h2 += 12
    if h2 > 23 or (h2, m2) <= (h1, m1):
        return None
    return f"{h1:02d}:{m1:02d}", f"{h2:02d}:{m2:02d}", (text[:m.start()] + " " + text[m.end():]).strip()


def parse_class(text):
    """(day, start, end, subject, room) from 'monday 9 to 10 data structures room 204', or a short reason string when something is missing."""
    got = parse_range(text)
    if not got:
        return "Say the times too, for example: add class Monday 9 to 10 data structures room 204."
    start, end, rest = got
    day = None
    for word in re.findall(r"[A-Za-z]+", rest):
        if len(word) >= 3 and weekday_of(word) is not None:
            day = weekday_of(word)
            rest = re.sub(rf"\b{word}\b", " ", rest, count=1, flags=re.I)
            break
    if day is None:
        return "Which day of the week is the class?"
    room = ""
    m = re.search(r"\b(?:in |at )?(room|lab|hall) ([\w-]+)\b", rest, re.I)
    if m:
        room = f"{m.group(1).title()} {m.group(2)}"
        rest = rest[:m.start()] + " " + rest[m.end():]
    subject = " ".join(re.sub(r"\b(?:on|every|at|from|class|for|a|the|add)\b", " ", rest, flags=re.I).split()).strip(" ,.")
    return (day, start, end, subject.title() if subject.islower() else subject, room) if subject else "What is the class called?"


# ---------- the brief ----------
def brief_lines(now=None, horizon=7):
    """{classes: [...], deadlines: [...]} as short strings for today's brief: today's classes and deadlines in the next `horizon` days."""
    now = now or datetime.now()
    today = now.date()
    return {"classes": [say_class(c) for c in classes_on(today)],
            "deadlines": [say_deadline(d, today) for d in due_within(horizon, today)][:5]}


def focus_hint(now=None):
    """A plain one line focus suggestion without a model: the nearest deadline, else the next class."""
    now = now or datetime.now()
    soon = [d for d in due_within(7, now.date()) if d["date"] >= now.date()]
    if soon:
        return f"Focus on {soon[0]['item']}, due {countdown(soon[0]['date'], now.date())}."
    nxt = next_class(now)
    if nxt:
        c, day = nxt
        return f"Next up is {c['subject']} at {c['start']}" + ("" if day == now.date() else f" on {FULL[c['day']].title()}") + "."
    return ""
