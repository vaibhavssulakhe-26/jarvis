"""Voice tools for watching pages and topics."""
from ..scheduling import monitor
from .screen import read_clip
from .tools import ToolError, tool


@tool("add_watch", 'args {"target": "<url or topic>", "every": <number>, "unit": "minutes or hours", "word": "<optional word to wait for>"} - watch a page or topic and say when it changes; use target "clipboard" for this page; minimum every 10 minutes')
def add_watch(args):
    target = str(args.get("target") or "").strip()
    if target.lower() in ("clipboard", "this page", "this"):
        clip = read_clip().strip()
        target = clip.split()[0] if clip else ""
        if not target.startswith("http"):
            raise ToolError("Copy the page address first, then ask me again.")
    if not target:
        raise ToolError("What should I watch?")
    interval = monitor.parse_interval(args.get("every"), args.get("unit") or "minutes")
    try:
        watch_id = monitor.add(target, interval, str(args.get("word") or ""))
    except monitor.WatchError as e:
        raise ToolError(f"I will not watch that: {e}.")
    every = f"{interval // 3600} hours" if interval % 3600 == 0 else f"{interval // 60} minutes"
    return f"Watching {target[:60]} every {every}. It is number {watch_id}."


@tool("list_watches", "args {} - list the pages and topics being watched")
def list_watches(args):
    items = monitor.rows()
    if not items:
        return "You are not watching anything."
    return "You are watching: " + ". ".join(monitor.label(w) for w in items) + "."


def _one(args):
    w = monitor.find(args.get("watch") or args.get("target") or "")
    if not w:
        raise ToolError("Which watch? Say its number, or part of its address.")
    return w


@tool("pause_watch", 'args {"watch": "<number or words>"} - pause a watch')
def pause_watch(args):
    w = _one(args)
    monitor.set_paused(w["id"], True)
    return f"Paused watch {w['id']}."


@tool("resume_watch", 'args {"watch": "<number or words>"} - resume a paused watch')
def resume_watch(args):
    w = _one(args)
    monitor.set_paused(w["id"], False)
    return f"Resumed watch {w['id']}."


@tool("remove_watch", 'args {"watch": "<number or words>"} - stop and delete a watch')
def remove_watch(args):
    w = _one(args)
    monitor.remove(w["id"])
    return f"Removed watch {w['id']}."
