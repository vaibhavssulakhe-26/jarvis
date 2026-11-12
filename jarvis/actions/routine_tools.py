"""Voice tools for routines and the calendar: list, add and run routines, and read today's agenda (read only)."""
import re
from datetime import date, timedelta

from ..routines import add, find, ical, load, run_one
from . import events
from .tools import ToolError, tool

TIME = re.compile(r"\b(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b", re.I)


def parse_when(text):
    """('HH:MM', text without the time) for 'at 9 pm', '21:30' or 'at 7'; (None, text) when there is no time."""
    for m in TIME.finditer(text):
        hour, minute, ampm = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower().replace(".", "")
        if not m.group(2) and not ampm and not re.match(r"\s*at\b", m.group(0), re.I):
            continue
        if ampm:
            if not 1 <= hour <= 12:
                continue
            hour = hour % 12 + (12 if ampm == "pm" else 0)
        if hour > 23 or minute > 59:
            continue
        return f"{hour:02d}:{minute:02d}", (text[:m.start()] + " " + text[m.end():]).strip()
    return None, text


@tool("list_routines", 'args {} - say the scheduled routines; for "list routines"')
def list_routines(args):
    rows = load()
    if not rows:
        return "You have no routines. Say add routine, then a time and what to do."
    text = "\n".join(f"{r['time']}  {r['name']}  ({r['instruction']})" for r in rows)
    print(text)
    events.emit("sys", text)
    return "You have " + ", ".join(f"{r['name']} at {r['time']}" for r in rows[:4]) + (f", and {len(rows) - 4} more." if len(rows) > 4 else ".")


@tool("add_routine", 'args {"text": "<time and what to do>"} - add a scheduled routine such as a briefing, inbox triage or notes reindex; for "add routine at 9 pm reindex my notes"')
def add_routine(args):
    text = " ".join(str(args.get("text") or "").split())
    when, rest = parse_when(text)
    rest = re.sub(r"^(?:every (?:day|night|morning)|daily|nightly|to|please|,)\s*", "", rest, flags=re.I).strip(" ,.")
    if not rest:
        raise ToolError("What should the routine do? I can brief you, triage your inbox or reindex your notes.")
    if when is None:
        raise ToolError("At what time? For example: add routine at 9 pm reindex my notes.")
    try:
        name = add(when, rest[:40], rest)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Added {name} at {when}. It runs every day, or at the next start if the laptop was off."


@tool("run_routine", 'args {"name": "<routine name>"} - run a routine now; for "run the inbox triage now"')
def run_routine(args):
    r = find(args.get("name"))
    if r is None or not r["action"]:
        raise ToolError("I do not have a routine like that. Say list routines to hear them.")
    ok, line = run_one(r)
    if not ok:
        raise ToolError(f"The {r['name']} routine did not finish: {line}.")
    return f"Done: {r['name']}, {line}."


@tool("calendar_today", 'args {"day": "today, tomorrow or a weekday"} - read events from the calendar link (read only); for "what is on my calendar"')
def calendar_today(args):
    if not ical.configured():
        raise ToolError("Add your private calendar link as CALENDAR_ICS_URL in the dot env file first. I only read it, I never change it.")
    word = str(args.get("day") or "today").lower()
    day = date.today() + timedelta(days=1) if "tomorrow" in word else date.today()
    for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")):
        if name in word:
            day = date.today() + timedelta(days=(i - date.today().weekday()) % 7)
    items = ical.day_events(day)
    label = "today" if day == date.today() else "tomorrow" if day == date.today() + timedelta(days=1) else f"on {day:%A}"
    if not items:
        return f"Nothing on your calendar {label}."
    text = "\n".join(f"{e['time']}  {e['title']}" + (f"  ({e['place']})" if e["place"] else "") for e in items)
    print(text)
    events.emit("sys", text)
    first = items[0]
    return f"You have {len(items)} thing{'s' if len(items) != 1 else ''} {label}. First, {first['time']} {first['title']}."
