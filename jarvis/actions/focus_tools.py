"""Voice tools for focus time and the morning start: the pomodoro, the good morning line, quick notes."""
import threading
from datetime import datetime

from .. import redact
from ..core import config
from ..memory import notes, rag
from ..scheduling import pomodoro
from . import study
from .tools import ToolError, tool


def _say_minutes(n):
    return f"{n} minute{'s' if n != 1 else ''}"


@tool("start_focus", 'args {"minutes": 25} - start a focus timer (pomodoro); for "start focus 25"')
def start_focus(args):
    try:
        minutes = int(float(args.get("minutes") or 0)) or None
    except (TypeError, ValueError):
        minutes = None
    if minutes is not None and minutes < 1:
        raise ToolError("A focus session needs at least one minute.")
    n = pomodoro.start("focus", minutes)
    return f"Focus started for {_say_minutes(n)}. I will tell you when time is up."


@tool("start_break", 'args {"minutes": 5} - start a break timer after a focus session; for "break"')
def start_break(args):
    try:
        minutes = int(float(args.get("minutes") or 0)) or None
    except (TypeError, ValueError):
        minutes = None
    n = pomodoro.start("break", minutes)
    return f"Break for {_say_minutes(n)}. Stretch, drink some water."


@tool("stop_focus", 'args {} - stop the focus or break timer; for "stop focus"')
def stop_focus(args):
    ended = pomodoro.stop()
    if not ended:
        return "No timer is running."
    kind, done = ended
    if kind == "break":
        return "Break stopped."
    return f"Focus stopped. I logged {_say_minutes(done)} of study." if done else "Focus stopped."


@tool("focus_left", 'args {} - say how much time is left on the focus timer; for "how long is left"')
def focus_left(args):
    cur = pomodoro.status()
    if not cur:
        return "No timer is running."
    mins = max(1, round(pomodoro.left() / 60))
    return f"{_say_minutes(mins)} left in your {cur['kind']}."


def _today_reminders():
    from ..scheduling import digest
    return digest.today_reminders()


@tool("good_morning", 'args {} - a short start to the day: date, reminders, the next roadmap item and the study streak; for "good morning"')
def good_morning(args):
    from ..routines import morning
    from ..voice import speech
    from . import events
    saved = morning.latest()
    if saved and saved["spoken"]:
        events.emit("sys", saved["text"])
        return speech.Full(saved["spoken"])
    now = datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    who = config.PET_NAME
    sentences = [f"Good {part}{', ' + who if who else ''}, it is {now:%A}, {now.day} {now:%B}."]
    mine = _today_reminders()
    if mine:
        sentences.append(f"You have {len(mine)} reminder{'s' if len(mine) > 1 else ''} today, starting with {mine[0]}.")
    else:
        sentences.append("You have no reminders today.")
    item = study.next_item()
    if item:
        sentences.append(f"Next on your roadmap: {item}.")
    streak = study.streak()
    if streak:
        sentences.append(f"Your study streak is {streak} day{'s' if streak != 1 else ''}.")
    return " ".join(sentences[:4])


def inbox_path():
    return notes.NOTES_DIR / "inbox.md"


@tool("quick_note", 'args {"text": "<the note>"} - add a line with the time to the notes inbox; for "note: buy a cable"')
def quick_note(args):
    text = redact.mask(" ".join(str(args.get("text") or "").split())[:1000])
    if not text:
        raise ToolError("What should I note?")
    path = inbox_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    first = not path.exists()
    with path.open("a") as f:
        if first:
            f.write("# Inbox\n\n")
        f.write(f"- [{datetime.now():%Y-%m-%d %H:%M}] {text}\n")
    threading.Thread(target=rag.update_if_changed, daemon=True).start()
    return "Noted."
