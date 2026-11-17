"""Voice commands for memory: forget something, say what is known, read back past conversations."""
from datetime import date

from ..memory import facts, memory
from .tools import ToolError, tool


def _forget_describe(args):
    what = str(args.get("what") or "").strip()
    hits = memory.find_facts(what) if what else []
    mine = facts.search(what, 50) if what else []
    if not hits and not mine:
        raise ToolError(f"I have nothing about {what or 'that'} to forget.")
    args["_hit"] = hits[0] if hits else None
    args["_topic"] = what
    if mine and not hits:
        return f"I will forget {len(mine)} remembered {'thing' if len(mine) == 1 else 'things'} about {what}."
    return f"I will forget that {hits[0][2]}."


@tool("forget", 'args {"what": "<words from the thing to forget>"} - delete a remembered fact or everything remembered about a topic; for "forget that ...", "forget <topic>"',
      risk="confirm", describe=_forget_describe)
def forget(args):
    if "_topic" not in args:
        _forget_describe(args)
    hit = args.get("_hit")
    if hit:
        memory.delete(hit[0], hit[1])
    facts.forget(args["_topic"])
    return "Okay, I have forgotten that."


@tool("recall_memory", 'args {"topic": "<words>"} - say what is remembered about a topic; for "what do you remember about X"')
def recall_memory(args):
    topic = str(args.get("topic") or "").strip()
    rows = facts.search(topic, 5)
    old = memory.find_facts(topic, 3) if topic else []
    lines = [r["text"] for r in rows] + [h[2] for h in old if h[2] not in {r["text"] for r in rows}]
    if not lines:
        return f"I do not remember anything about {topic or 'that'}."
    return "Here is what I remember about " + (topic or "you") + ". " + ". ".join(l.rstrip(".") for l in lines[:5]) + "."


@tool("show_memory", 'args {} - show everything remembered, newest first; for "show my memory"')
def show_memory(args):
    rows = facts.listing()
    if not rows:
        return "I have not saved any memories yet."
    return "What I remember:\n" + "\n".join(f"- {r['text']} ({r['date']})" for r in rows[:30])


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
