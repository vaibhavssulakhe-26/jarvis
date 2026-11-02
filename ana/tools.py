"""Everything Ana can do. Each tool is one small function with a risk level."""
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import brain, config, events, reminders

HOME = Path.home()
TOOLS = {}


class ToolError(Exception):
    pass


def tool(name, doc, risk="safe", describe=None, skip=None):
    def wrap(fn):
        TOOLS[name] = {"fn": fn, "doc": name + ": " + doc, "risk": risk,
                       "describe": describe, "skip": skip}
        return fn
    return wrap


def prompt():
    lines = ["- " + t["doc"] for t in TOOLS.values()]
    lines += ['- ask: a needed detail is missing, or you want to ask the user something back; put the question in "say"',
              '- chat: answer a question or just talk, in two to four short sentences in "say"',
              '- none: the text is noise or not meant for you']
    return "\n".join(lines)


def _launch(cmd):
    if shutil.which(cmd[0]) is None:
        raise ToolError(f"{cmd[0]} is not installed.")
    subprocess.Popen(cmd, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _browser(url):
    pref = config.get("ANA_BROWSER")
    _launch([pref, url] if pref and shutil.which(pref) else ["xdg-open", url])


_STOP = {"the", "a", "an", "to", "of", "on", "in", "at", "and", "or", "my", "me", "you", "your", "i",
         "is", "it", "for", "please", "can", "could", "would", "will", "play", "send", "message",
         "say", "tell", "from", "by", "with", "some", "song", "songs", "music", "video", "videos",
         "youtube", "whatsapp", "that", "this", "her", "him", "his", "she", "he", "we", "us", "so"}


def heard_recently(text):
    """True if at least one meaningful word of text was actually said by the user."""
    said = set(re.findall(r"[a-z0-9]+", " ".join(brain.RECENT).lower()))
    words = [w for w in re.findall(r"[a-z0-9]+", str(text).lower()) if w not in _STOP and len(w) > 1]
    return (not words) or any(w in said for w in words)


def stamped_name(text, fallback, ext):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:40] or fallback
    return f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{slug}{ext}"


def read_battery():
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            return int((d / "capacity").read_text()), (d / "status").read_text().strip().lower()
        except (OSError, ValueError):
            continue
    return None, ""


# ---------- system ----------
@tool("battery", "args {} - tell the battery level")
def battery(args):
    pct, status = read_battery()
    if pct is None:
        raise ToolError("I could not read the battery.")
    return f"Battery is at {pct} percent and {status}."


@tool("system_status", "args {} - memory, disk space and uptime")
def system_status(args):
    mem = {}
    for line in open("/proc/meminfo"):
        key, value = line.split(":", 1)
        mem[key] = int(value.split()[0])
    total = mem["MemTotal"] / 1048576
    used = (mem["MemTotal"] - mem["MemAvailable"]) / 1048576
    disk = shutil.disk_usage(str(HOME))
    up = float(open("/proc/uptime").read().split()[0])
    return (f"Memory {used:.1f} of {total:.1f} gigabytes in use. Disk has {disk.free / 1e9:.0f} gigabytes free. "
            f"Up for {int(up // 3600)} hours {int(up % 3600 // 60)} minutes.")


def _wp(*a):
    subprocess.run(["wpctl", *a], timeout=5)


@tool("set_volume", 'args {"percent": 0 to 100}')
def set_volume(args):
    try:
        n = max(0, min(100, int(float(args.get("percent")))))
    except (TypeError, ValueError):
        raise ToolError("What volume level do you want?")
    _wp("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{n / 100:.2f}")
    return f"Volume {n} percent."


@tool("volume_up", "args {} - raise the volume a little")
def volume_up(args):
    _wp("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "10%+")
    return "Louder."


@tool("volume_down", "args {} - lower the volume a little")
def volume_down(args):
    _wp("set-volume", "@DEFAULT_AUDIO_SINK@", "10%-")
    return "Quieter."


@tool("mute", "args {} - mute the laptop sound")
def mute(args):
    _wp("set-mute", "@DEFAULT_AUDIO_SINK@", "1")
    return "Muted."


@tool("unmute", "args {} - unmute the laptop sound")
def unmute(args):
    _wp("set-mute", "@DEFAULT_AUDIO_SINK@", "0")
    return "Sound is back."


@tool("screenshot", "args {} - take a screenshot of the whole screen")
def screenshot(args):
    if shutil.which("spectacle") is None:
        raise ToolError("Spectacle is not installed.")
    folder = HOME / "Pictures"
    folder.mkdir(exist_ok=True)
    path = folder / datetime.now().strftime("shot-%Y%m%d-%H%M%S.png")
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", str(path)], timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not path.exists():
        time.sleep(1.5)
    if not path.exists():
        raise ToolError("I could not save the screenshot.")
    return "Screenshot saved in your Pictures folder."


@tool("lock_screen", "args {} - lock the screen")
def lock_screen(args):
    _launch(["loginctl", "lock-session"])
    return "Locking the screen."


# ---------- reminders and notes ----------
@tool("set_reminder", 'args {"task": "<short phrase>", "when": "YYYY-MM-DD HH:MM"} using 24-hour local time; for relative times such as in thirty seconds or in ten minutes use "in_seconds": <number> instead of when')
def set_reminder(args):
    task = str(args.get("task", "")).strip() or "reminder"
    when = None
    try:
        secs = float(args.get("in_seconds"))
        if 0 < secs <= 30 * 86400:
            when = datetime.now() + timedelta(seconds=secs)
    except (TypeError, ValueError):
        pass
    raw = str(args.get("when", "")).strip()
    if when is None and raw:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S"):
            try:
                when = datetime.strptime(raw, fmt)
                break
            except ValueError:
                continue
        if when is None:
            import dateparser
            when = dateparser.parse(raw, settings={"PREFER_DATES_FROM": "future"})
    if when is None:
        print(f"  (could not read the reminder time: {args})")
        raise ToolError("I could not work out the time. When should I remind you?")
    if when <= datetime.now():
        raise ToolError("That time has already passed.")
    reminders.add(task, when)
    return f"Okay. Reminder to {task}, {reminders.friendly(when)}."


@tool("list_reminders", "args {} - read out the pending reminders")
def list_reminders(args):
    return reminders.describe()


@tool("clear_reminders", "args {} - delete all pending reminders")
def clear_reminders(args):
    reminders.clear()
    return "Cleared your pending reminders."


@tool("take_note", 'args {"text": "..."} - add a line to the notes file')
def take_note(args):
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("What should I write down?")
    notes = HOME / "Documents" / "assistant-notes.md"
    notes.parent.mkdir(parents=True, exist_ok=True)
    with open(notes, "a") as f:
        f.write(f"- {datetime.now().strftime('%Y-%m-%d %H:%M')}  {text[:1000]}\n")
    return "Noted."


# ---------- web ----------
@tool("web_search", 'args {"query": "..."} - open a web search in the browser')
def web_search(args):
    q = str(args.get("query", "")).strip()
    if not q:
        raise ToolError("What should I search for?")
    _browser("https://duckduckgo.com/?q=" + quote(q))
    return f"Searching for {q}."


# ---------- writing and code ----------
@tool("draft_text", 'args {"title": "<2 to 4 words>", "text": "<the full draft>"} - write an email or message draft for the user to review; never sends anything')
def draft_text(args):
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("There was nothing to draft.")
    folder = HOME / "Documents" / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / stamped_name(args.get("title", "draft"), "draft", ".txt")).write_text(text[:6000] + "\n")
    print("\n" + text + "\n")
    events.emit("sys", text)
    copied = False
    if shutil.which("wl-copy"):
        subprocess.run(["wl-copy"], input=text.encode(), timeout=5,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        copied = True
    return "I wrote the draft and saved it in your drafts folder" + (" and copied it to the clipboard." if copied else ".")


@tool("write_file", 'args {"path": "<relative path such as todo-app/main.py>", "content": "<the full file text>"} - create a new code or text file inside the ana-projects folder and open it in the editor; never overwrites')
def write_file(args):
    root = HOME / "ana-projects"
    root.mkdir(exist_ok=True)
    rel = str(args.get("path", "")).strip().lstrip("/")
    content = str(args.get("content", ""))
    if not rel or not content.strip():
        raise ToolError("I need a file name and what to write in it.")
    p = (root / rel).resolve()
    try:
        parts = p.relative_to(root.resolve()).parts
    except ValueError:
        raise ToolError("I only write inside the ana-projects folder.")
    if not parts or any(x.startswith(".") for x in parts):
        raise ToolError("I do not write hidden files.")
    if p.exists():
        raise ToolError("That file already exists, so I will not overwrite it.")
    if len(content) > 20000:
        raise ToolError("That file is too big for me to write in one go.")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    editor = next((e for e in ("code", "antigravity") if shutil.which(e)), None)
    if editor:
        _launch([editor, str(p)])
    return f"Created {p.name} in ana-projects" + (" and opened it." if editor else ".")


# ---------- power ----------
def _power_desc(verb):
    return lambda args: f"I will {verb}."


@tool("suspend", "args {} - suspend the laptop", risk="confirm", describe=_power_desc("suspend the laptop"))
def suspend(args):
    _launch(["systemctl", "suspend"])
    return "Suspending."


@tool("shutdown", "args {} - power the laptop off", risk="confirm", describe=_power_desc("shut the laptop down"))
def shutdown(args):
    _launch(["systemctl", "poweroff"])
    return "Shutting down."


@tool("restart", "args {} - restart the laptop", risk="confirm", describe=_power_desc("restart the laptop"))
def restart(args):
    _launch(["systemctl", "reboot"])
    return "Restarting."


# these modules register their tools on import, so they must load after the registry above
from . import apps, media, messaging, research  # noqa: E402,F401
