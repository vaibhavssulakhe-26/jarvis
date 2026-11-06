"""Voice commands for memory: forget something, say what is known, read back past conversations."""
from datetime import date

from ..memory import memory
from .tools import ToolError, tool


def _forget_describe(args):
    what = str(args.get("what") or "").strip()
    hits = memory.find_facts(what) if what else []
    if not hits:
        raise ToolError(f"I have nothing about {what or 'that'} to forget.")
    args["_hit"] = hits[0]
    return f"I will forget that {hits[0][2]}."


@tool("forget", 'args {"what": "<words from the thing to forget>"} - delete a remembered fact; for "forget that ..."',
      risk="confirm", describe=_forget_describe)
def forget(args):
    hit = args.get("_hit")
    if not hit:
        _forget_describe(args)
        hit = args["_hit"]
    memory.delete(hit[0], hit[1])
    return "Okay, I have forgotten that."


@tool("what_do_you_know", 'args {} - read back what is remembered about the user; for "what do you know about me"')
def what_do_you_know(args):
    facts = memory.top_facts()
    people = memory.people_summary()
    if not facts and not people:
        return "I do not know much about you yet. Tell me something and say remember that."
    line = "Here is what I remember. " + ". ".join(facts) + "." if facts else ""
    if people:
        line += " People you have mentioned: " + ", ".join(people) + "."
    return line.strip()


@tool("recall_day", 'args {"when": "<yesterday, today or a date>"} - say what was talked about on a day; for "what did we talk about yesterday"')
def recall_day(args):
    day = memory.day_from_words(args.get("when") or "yesterday")
    if not isinstance(day, date):
        raise ToolError("Which day do you mean?")
    eps = memory.episodes_on(day)
    label = "that day" if day != date.today() else "today"
    if not eps:
        return f"I have no conversation summaries for {label}."
    return f"On {day.strftime('%A %d %B')} we talked about: " + " ".join(eps[:3])
