"""Voice tools for the distraction guard, focus mode and screen time."""
import time
from datetime import datetime

from ..core import state
from ..scheduling import guard
from . import windows
from .tools import ToolError, tool

LABELS = {"work": "working", "learning": "learning", "music": "music", "entertainment": "entertainment",
          "social": "social media", "other": "other things"}


def _until(phrase, default_minutes):
    from .reminder_tools import snooze_time
    when = snooze_time(phrase) if str(phrase or "").strip() else None
    if when is None:
        return time.time() + default_minutes * 60
    return when.timestamp()


@tool("guard_switch", 'args {"on": true or false} - turn the distraction guard on or off; for "turn on focus guard", "turn it off"')
def guard_switch(args):
    on = args.get("on") in (True, "true", "yes", "on", 1)
    if on and windows.active_window(max_age=0) is None:
        state.update(guard=False)
        raise ToolError("I cannot read the active window here, so the guard stays off. Window reading is not available here.")
    state.update(guard=on)
    if on:
        guard.start()
        return "Focus guard is on. Titles stay on this laptop unless one is unclear, then a few go to the brain together. I keep minutes, not titles."
    return "Focus guard is off."


@tool("focus_mode", 'args {"for": "90 minutes"} - strict study time: the guard speaks up after five minutes and reminders wait; also "end focus mode"')
def focus_mode(args):
    phrase = str(args.get("for") or "")
    if str(args.get("end")).lower() in ("true", "1") or phrase.lower() in ("off", "end", "stop"):
        state.update(focus_until=0.0)
        return "Focus mode is over. Held reminders will come through now."
    until = _until(phrase, 60)
    state.update(focus_until=until, guard=True if state.get("guard") is None else state.get("guard"))
    guard.start()
    when = datetime.fromtimestamp(until).strftime("%I:%M %p").lstrip("0")
    return f"Focus mode until {when}. I will keep reminders quiet and nudge you after five minutes off track."


@tool("take_break", 'args {"for": "two hours"} - stop distraction nudges; with no length, for the rest of the day; for "I am on a break", "leave me alone for two hours"')
def take_break(args):
    phrase = str(args.get("for") or "")
    if phrase.strip():
        until = _until(phrase, 120)
    else:
        until = datetime.now().replace(hour=23, minute=59, second=0).timestamp()
    state.update(break_until=until)
    when = datetime.fromtimestamp(until).strftime("%I:%M %p").lstrip("0")
    return f"Enjoy your break. I will stay quiet until {when}."


@tool("screen_time", 'args {} - say how much time went on study versus entertainment today; for "what\'s my screen time", "how did I spend my time today"')
def screen_time(args):
    mins = guard.minutes_today()
    if not mins:
        return "I have no screen time recorded today. Turn on the distraction guard and I will start counting."
    study = mins.get("work", 0) + mins.get("learning", 0)
    fun = mins.get("entertainment", 0) + mins.get("social", 0)
    line = f"Today: {study:.0f} minutes of study and work, {fun:.0f} minutes of entertainment and social media"
    if mins.get("music"):
        line += f", and {mins['music']:.0f} minutes of music"
    return line + "."
