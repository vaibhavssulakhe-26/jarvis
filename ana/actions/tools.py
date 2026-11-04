"""Everything Ana can do. Each tool is one small function with a risk level."""
import re
import shutil
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import events
from ..brain import brain
from ..core import config
from ..memory import memory
from ..scheduling import reminders

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


def cpu_temp():
    import psutil
    try:
        temps = psutil.sensors_temperatures()
    except (AttributeError, OSError):
        return None
    for chip in ("k10temp", "coretemp", "zenpower", "cpu_thermal", "acpitz"):
        for t in temps.get(chip, []):
            if t.current and t.current > 0:
                return t.current
    return None


@tool("system_status", "args {} - battery, charging, memory, processor load and temperature")
def system_status(args):
    import psutil
    parts = []
    pct, status = read_battery()
    if pct is not None:
        parts.append(f"Battery {pct} percent, {status}")
    mem = psutil.virtual_memory()
    parts.append(f"memory {mem.used / 2**30:.1f} of {mem.total / 2**30:.1f} gigabytes in use")
    load = f"processor at {psutil.cpu_percent(interval=0.3):.0f} percent"
    temp = cpu_temp()
    parts.append(load + (f" and {temp:.0f} degrees" if temp else ""))
    line = ", ".join(parts) + "."
    return line[0].upper() + line[1:]


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


def _step(args):
    try:
        return max(1, min(100, int(float(args.get("by", 10)))))
    except (TypeError, ValueError):
        return 10


@tool("volume_up", 'args {} to raise the volume a little, or {"by": percent} to raise it by that much')
def volume_up(args):
    _wp("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{_step(args)}%+")
    return "Louder."


@tool("volume_down", 'args {} to lower the volume a little, or {"by": percent} to lower it by that much')
def volume_down(args):
    _wp("set-volume", "@DEFAULT_AUDIO_SINK@", f"{_step(args)}%-")
    return "Quieter."


_before_mute = [None]


def get_volume():
    r = subprocess.run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"], capture_output=True, text=True, timeout=5)
    m = re.search(r"([0-9.]+)", r.stdout)
    return round(float(m.group(1)) * 100) if m else None


@tool("mute", "args {} - mute the laptop sound, remembering the volume level")
def mute(args):
    level = get_volume()
    if level:
        _before_mute[0] = level
    _wp("set-volume", "@DEFAULT_AUDIO_SINK@", "0")
    return "Muted."


@tool("unmute", "args {} - unmute the laptop sound, or restore the volume to where it was before muting")
def unmute(args):
    level = _before_mute[0]
    if level is None:
        level = get_volume() or 40
    _wp("set-mute", "@DEFAULT_AUDIO_SINK@", "0")
    _wp("set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", f"{level / 100:.2f}")
    _before_mute[0] = None
    return f"Sound is back at {level} percent."


@tool("screenshot", "args {} - take a screenshot of the whole screen")
def screenshot(args):
    folder = HOME / "Pictures"
    folder.mkdir(exist_ok=True)
    capture_screen(folder / datetime.now().strftime("shot-%Y%m%d-%H%M%S.png"))
    return "Screenshot saved in your Pictures folder."


def capture_screen(path):
    # scrot and gnome-screenshot only work on X11 or GNOME, so they are fallbacks behind spectacle
    for cmd in (["spectacle", "-b", "-n", "-f", "-o", str(path)],
                ["gnome-screenshot", "-f", str(path)],
                ["scrot", "-o", str(path)]):
        if shutil.which(cmd[0]):
            break
    else:
        raise ToolError("I need spectacle to take a screenshot.")
    subprocess.run(cmd, timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if not path.exists():
        time.sleep(1.5)
    if not path.exists():
        raise ToolError("I could not save the screenshot.")


@tool("lock_screen", "args {} - lock the screen")
def lock_screen(args):
    _launch(["loginctl", "lock-session"])
    return "Locking the screen."


# ---------- reminders and notes ----------
@tool("set_reminder", 'args {"task": "<short phrase>", "when": "YYYY-MM-DD HH:MM"} using 24-hour local time; for relative times such as in thirty seconds or in ten minutes use "in_seconds": <number> instead of when; for a repeating reminder such as every 30 minutes add "every_minutes": <number>, with when or in_seconds only if the user said when it starts')
def set_reminder(args):
    task = str(args.get("task", "")).strip() or "reminder"
    when = None
    every = None
    try:
        mins = float(args.get("every_minutes"))
        if 1 <= mins <= 7 * 1440:
            every = int(mins * 60)
    except (TypeError, ValueError):
        pass
    if every and not args.get("in_seconds") and not str(args.get("when", "")).strip():
        when = datetime.now() + timedelta(seconds=every)
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
    reminders.add(task, when, every)
    if every:
        return f"Okay. I will remind you to {task} {reminders.interval(every)}, starting {reminders.friendly(when)}."
    return f"Okay. Reminder to {task}, {reminders.friendly(when)}."


@tool("cancel_reminder", 'args {"task": "<a word or two from the reminder>"} - stop one reminder, including a repeating one')
def cancel_reminder(args):
    task = str(args.get("task", "")).strip()
    if not task:
        raise ToolError("Which reminder should I stop?")
    n = reminders.cancel(task)
    if not n:
        raise ToolError(f"I could not find a reminder about {task}.")
    return f"Stopped the {task} reminder." if n == 1 else f"Stopped {n} reminders about {task}."


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


# ---------- memory ----------
@tool("remember", 'args {"fact": "short statement about the user", "name": "their name, only if they gave it"} - keep a lasting personal fact for future conversations')
def remember(args):
    fact, name = str(args.get("fact") or "").strip(), str(args.get("name") or "").strip()
    if not (fact or name):
        raise ToolError("I did not catch what to remember.")
    memory.remember(fact, name)
    return "Got it, I will remember that."


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
from . import apps, media, messaging, screen  # noqa: E402,F401
from ..research import research  # noqa: E402,F401
