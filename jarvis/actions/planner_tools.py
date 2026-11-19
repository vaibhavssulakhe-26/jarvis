"""Voice tools for the timetable, deadlines, quick tasks and alerts. All of it is local files under data/; nothing here uses a model."""
from datetime import date, timedelta

from .. import alerts, tasks, timetable
from ..routines import ical
from . import events
from .tools import ToolError, tool

NUMBERS = {w: i for i, w in enumerate("zero one two three four five six seven eight nine ten".split())}


def _show(text):
    print(text)
    events.emit("sys", text)


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


@tool("next_class", 'args {} - say the next class from the timetable; for "next class"')
def next_class(args):
    if not timetable.classes():
        raise ToolError("Your timetable is empty. Say add class, then the day, the times and the subject, or edit data/timetable.md.")
    got = timetable.next_class()
    if got is None:
        return "No more classes in the coming week."
    c, day = got
    when = "today" if day == date.today() else "tomorrow" if day == date.today() + timedelta(days=1) else timetable.FULL[c["day"]].title()
    return f"Your next class is {c['subject']} {when} at {c['start']}" + (f", {c['room']}." if c["room"] else ".")


@tool("today_schedule", 'args {} - say today\'s classes and calendar events; for "what is today\'s schedule"')
def today_schedule(args):
    today = date.today()
    rows = [timetable.say_class(c) + f" to {c['end']}" for c in timetable.classes_on(today)]
    if ical.configured():
        try:
            rows += [f"{e['time']} {e['title']}" for e in ical.day_events(today)]
        except Exception:
            pass
    due = [d for d in timetable.deadlines() if d["date"] == today]
    if not rows and not due:
        return "Nothing scheduled today." if timetable.classes() or ical.configured() else "I have no timetable yet. Say add class, or edit data/timetable.md."
    _show("\n".join(rows + [f"Due today: {d['item']}" for d in due]))
    line = f"Today you have {_plural(len(rows), 'thing')}, starting with {rows[0]}." if rows else "No classes today."
    return line + (f" Due today: {due[0]['item']}." if due else "")


@tool("whats_due", 'args {} - say the deadlines in the next seven days; for "what is due this week"')
def whats_due(args):
    items = [d for d in timetable.due_within(7) if d["date"] >= date.today()]
    if not items:
        return "Nothing due this week." if timetable.deadlines() else "No deadlines saved yet. Say add deadline, then the item and a date."
    _show("\n".join(timetable.say_deadline(d) for d in items))
    return f"{_plural(len(items), 'deadline')} this week. First, " + timetable.say_deadline(items[0]) + "."


@tool("add_deadline", 'args {"item": "<what is due>", "on": "<date in words>"} - save a deadline; for "add deadline report on friday"')
def add_deadline(args):
    when = timetable.parse_date(str(args.get("on") or ""))
    if when is None:
        raise ToolError("Which date? For example: add deadline report on 20 November.")
    try:
        item = timetable.add_deadline(str(args.get("item") or ""), when)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Saved {item}, due {timetable.countdown(when)}, {when:%A %d %B}."


@tool("add_class", 'args {"text": "<day, times, subject and room>"} - add a class to the timetable; for "add class monday 9 to 10 data structures room 204"')
def add_class(args):
    got = timetable.parse_class(str(args.get("text") or ""))
    if isinstance(got, str):
        raise ToolError(got)
    day, start, end, subject, room = got
    try:
        timetable.add_class(day, start, end, subject, room)
    except ValueError as e:
        raise ToolError(str(e))
    return f"Added {subject} on {timetable.FULL[day].title()}, {start} to {end}."


@tool("add_task", 'args {"text": "<the task>"} - save a quick task with today\'s date; for "task: buy a cable"')
def add_task(args):
    try:
        text = tasks.add(args.get("text"))
    except ValueError as e:
        raise ToolError(str(e))
    return f"Task saved: {text}."


@tool("list_tasks", 'args {} - say the open tasks; for "list tasks"')
def list_tasks(args):
    items = tasks.open_items()
    if not items:
        return "No open tasks."
    _show(tasks.describe())
    return f"You have {_plural(len(items), 'open task')}. First, {items[0]['text']}."


@tool("task_done", 'args {"number": "<task number from the list>"} - mark an open task done; for "done 2"')
def task_done(args):
    raw = str(args.get("number") or "").strip().lower()
    number = int(raw) if raw.isdigit() else NUMBERS.get(raw)
    if number is None:
        raise ToolError("Which task number?")
    try:
        return f"Done: {tasks.done(number)}."
    except ValueError as e:
        raise ToolError(str(e))


@tool("clear_done_tasks", 'args {} - remove finished tasks from the list; for "clear done"')
def clear_done_tasks(args):
    n = tasks.clear_done()
    return f"Cleared {_plural(n, 'finished task')}." if n else "No finished tasks to clear."


@tool("show_alerts", 'args {} - say recent failures of routines and scheduled jobs; for "show alerts"')
def show_alerts(args):
    rows = alerts.lines(5)
    if not rows:
        return "No alerts."
    _show("\n".join(rows))
    return f"{_plural(alerts.count(), 'alert')}. The latest: {rows[0].split('  ', 1)[-1]}."


@tool("clear_alerts", 'args {} - clear the alert list; for "clear alerts"')
def clear_alerts(args):
    n = alerts.clear()
    return f"Cleared {_plural(n, 'alert')}." if n else "No alerts to clear."
