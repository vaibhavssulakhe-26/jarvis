"""Answering a reminder that just went off: got it, snooze, stop repeating, move to a better time."""
import re
import time
from datetime import datetime, timedelta

from ..scheduling import reminders
from .tools import ToolError, tool

WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "ten": 10, "fifteen": 15,
         "twenty": 20, "thirty": 30, "forty": 40, "forty five": 45, "sixty": 60, "ninety": 90}
UNITS = {"sec": 1, "second": 1, "min": 60, "minute": 60, "hour": 3600, "hr": 3600}
PARTS_OF_DAY = (("tonight", 21), ("night", 21), ("evening", 18), ("afternoon", 14), ("morning", 9))


def snooze_time(phrase):
    t = str(phrase or "").lower().strip()
    now = datetime.now()
    for word, hour in PARTS_OF_DAY:
        if word in t:
            when = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            return when if when > now and "tomorrow" not in t else when + timedelta(days=1)
    if re.search(r"\bhalf an? hour\b", t):
        return now + timedelta(minutes=30)
    m = re.search(r"(\d+(?:\.\d+)?|forty five|[a-z]+)\s*(sec|second|min|minute|hour|hr)", t)
    if m:
        n = float(m.group(1)) if m.group(1)[0].isdigit() else WORDS.get(m.group(1))
        if n:
            return now + timedelta(seconds=n * UNITS[m.group(2)])
    if not t or t in ("later", "a bit", "for a bit"):
        return now + timedelta(minutes=10 if not t else 60)
    import dateparser
    return dateparser.parse(t, settings={"PREFER_DATES_FROM": "future"})


@tool("ack_reminder", "args {} - the user says they have seen the reminder that just went off")
def ack_reminder(args):
    got = reminders.acknowledge()
    if not got:
        raise ToolError("There is no reminder waiting for an answer.")
    return got[2] or "Okay."


@tool("snooze_reminder", 'args {"for": "20 minutes"} or {"until": "tonight"} - push the reminder that just went off to later; for "snooze for 20 minutes", "remind me again tonight"')
def snooze_reminder(args):
    phrase = str(args.get("for") or args.get("until") or "")
    when = snooze_time(phrase)
    if when is None or when <= datetime.now():
        raise ToolError("I could not work out when. Say for example snooze for twenty minutes.")
    got = reminders.snooze(when)
    if not got:
        raise ToolError("There is no reminder to snooze right now.")
    text, count, suggestion = got
    line = f"Okay, I will remind you about {text} {reminders.friendly(when)}."
    if suggestion:
        from ..core import main as core
        core.PENDING.clear()
        core.PENDING.update({"action": "move_reminder", "args": {"text": text, "time": suggestion},
                             "until": time.time() + 60})
        said = datetime.strptime(suggestion, "%H:%M").strftime("%I:%M %p").lstrip("0")
        line += f" You have snoozed this {count} times. Want me to move it to a better time, around {said}?"
    return line


@tool("move_reminder", 'args {"text": "<the reminder>", "time": "HH:MM"} - move a reminder to a new time of day')
def move_reminder(args):
    when = reminders.move(str(args.get("text") or ""), str(args.get("time") or ""))
    return f"Done. {args.get('text')} is now {reminders.friendly(when)}."


@tool("stop_repeating", "args {} - stop the repeating reminder that just went off; for \"stop repeating this one\"")
def stop_repeating(args):
    text = reminders.stop_repeating()
    if not text:
        raise ToolError("There is no repeating reminder to stop right now.")
    return f"Okay, I will stop repeating {text}."
