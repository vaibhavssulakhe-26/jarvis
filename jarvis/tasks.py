"""Quick tasks in data/tasks.md, one per line: `- [ ] 2026-11-17 buy a cable`. Edit the file freely; Jarvis reads it as it is."""
import re
from datetime import date

from . import redact
from .core import config

LINE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(?:(\d{4}-\d{2}-\d{2})\s+)?(.+?)\s*$")
HEAD = "# Tasks\n\n"
MAX = 200


def path():
    return config.DATA / "tasks.md"


def rows():
    """[{done, date, text}] in file order."""
    try:
        lines = path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        m = LINE.match(line)
        if m:
            out.append({"done": m.group(1) != " ", "date": m.group(2) or "", "text": m.group(3)})
    return out


def save(items):
    path().parent.mkdir(parents=True, exist_ok=True)
    path().write_text(HEAD + "".join(f"- [{'x' if r['done'] else ' '}] {r['date']} {r['text']}".replace("]  ", "] ") + "\n" for r in items), encoding="utf-8")


def add(text):
    text = " ".join(redact.mask(str(text)).split())[:140].strip(" .,;:-")
    if not text:
        raise ValueError("What is the task?")
    items = rows()
    if len(items) >= MAX:
        raise ValueError("The task list is full. Say clear done to tidy it.")
    items.append({"done": False, "date": date.today().isoformat(), "text": text})
    save(items)
    return text


def open_items():
    return [r for r in rows() if not r["done"]]


def done(number):
    """Mark the number-th open task (as listed) done and return its text."""
    items = rows()
    open_ones = [r for r in items if not r["done"]]
    if not 1 <= number <= len(open_ones):
        raise ValueError(f"I have {len(open_ones)} open task{'s' if len(open_ones) != 1 else ''}." if open_ones else "You have no open tasks.")
    open_ones[number - 1]["done"] = True
    save(items)
    return open_ones[number - 1]["text"]


def clear_done():
    items = rows()
    keep = [r for r in items if not r["done"]]
    if len(keep) != len(items):
        save(keep)
    return len(items) - len(keep)


def describe():
    items = open_items()
    if not items:
        return "No open tasks."
    return "\n".join(f"{i}. {r['text']}" + (f" ({r['date']})" if r["date"] else "") for i, r in enumerate(items, 1))
