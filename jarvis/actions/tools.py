"""Everything Jarvis can do. Each tool is one small function with a risk level."""
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


# trigger words per tool: a new tool needs one entry here. Words match the start of a word in the sentence.
TRIGGERS = {
    "time_date": "time date day today clock",
    "battery": "battery charge charging",
    "system_status": "system status memory ram cpu processor temperature laptop computer",
    "set_volume": "volume sound louder quieter loud quiet",
    "volume_up": "volume sound louder up raise increase",
    "volume_down": "volume sound quieter down lower decrease reduce",
    "mute": "mute silence",
    "unmute": "unmute restore sound volume",
    "screenshot": "screenshot screen grab capture",
    "lock_screen": "lock",
    "set_reminder": "remind reminder every minutes hours tomorrow tonight alarm",
    "cancel_reminder": "cancel stop reminder reminders repeating",
    "list_reminders": "reminders pending list",
    "clear_reminders": "clear delete reminders",
    "take_note": "note write jot",
    "read_notes": "note notes noted read",
    "list_notes": "notes list topics",
    "search_notes": "notes search",
    "append_to_note": "add append note",
    "delete_note": "delete remove note notes",
    "find_file": "find file where locate",
    "ask_about_file": "file document pdf says about",
    "read_aloud_file": "read aloud file text",
    "web_search": "search google look browse",
    "draft_text": "draft email letter write compose message application",
    "build_project": "build create make write code script program website web app html page project",
    "edit_file": "edit change modify update add file code",
    "find_bugs": "bugs bug debug fix error check code file",
    "run_project": "run execute start program project code",
    "remember": "remember",
    "snooze_reminder": "snooze again later tonight",
    "stop_repeating": "stop repeating",
    "ack_reminder": "okay done thanks",
    "move_reminder": "move reminder time",
    "morning_briefing": "morning briefing day today digest",
    "add_watch": "watch monitor changes change",
    "list_watches": "watches watching list",
    "pause_watch": "pause watch",
    "resume_watch": "resume watch",
    "remove_watch": "remove stop watch",
    "check_email": "email emails mail inbox unread gmail",
    "check_spam": "spam junk email emails mail",
    "open_email": "open email inbox gmail mail",
    "rate_sender": "important sender email",
    "guard_switch": "distraction guard turn",
    "focus_mode": "focus mode study",
    "take_break": "break leave alone",
    "screen_time": "screen time spend",
    "forget": "forget",
    "what_do_you_know": "know remember about",
    "recall_day": "talk talked discuss yesterday conversation",
    "suspend": "suspend sleep",
    "shutdown": "shutdown shut power off",
    "restart": "restart reboot",
    "open_app": "open launch start app",
    "open_folder": "open folder downloads documents pictures videos music desktop projects",
    "play_media": "play song music video youtube listen",
    "play_next": "next another different skip",
    "media": "pause resume next previous skip song track",
    "message_contact": "message send text whatsapp tell mom",
    "send_screenshot": "send screenshot whatsapp",
    "describe_screen": "screen see look showing",
    "read_clipboard": "clipboard copied copy paste",
    "summarise_file": "summarise summarize summary pdf file document read synopsis",
    "research": "research find out news latest hackathon search events",
    "open_url": "open link url website page",
    "translate": "translate translation hindi kannada marathi tamil telugu spanish french german",
    "debug_clipboard": "explain error debug code clipboard fix bug",
    "send_to_device": "send phone laptop handoff share",
    "clip_monitor_switch": "clipboard monitor watcher",
    "research_topic": "research topic sources cited find out about",
    "open_sources": "sources links show open",
    "help_topic": "help how need topic understand learn",
    "open_palette": "palette command box",
    "close_app": "close quit exit app window",
    "switch_app": "switch focus window app",
    "minimise_window": "minimise minimize window hide",
    "open_path": "open file folder document pdf",
    "brightness": "brightness brighter dim dimmer screen",
    "open_site": "open website site go",
    "change_voice": "voice change male female british accent",
    "what_voice": "voice using",
    "proactive_level": "chattier quieter talk more less",
    "proactive_quiet": "stop talking quiet hours",
    "set_language": "listen reply language hindi kannada english",
}
ALWAYS = {"remember"}
MAX_TOOLS = 5
MAX_DOC = 300
SMALL_TALK = ("hey", "hi", "hello", "good morning", "good afternoon", "good evening", "good night", "thanks", "thank you",
              "how are you", "how s it going", "how are things", "what s up", "who are you", "what is your name",
              "what s your name", "can you hear me", "do you hear me", "are you there", "are you awake",
              "are you listening", "bye", "goodbye", "nice", "cool", "great", "awesome", "tell me a joke",
              "i m bored", "i m tired", "i m stressed", "i m sad", "i m happy")


def small_talk(text):
    t = " ".join(re.findall(r"[a-z0-9]+", str(text).lower()))
    return len(t.split()) <= 8 and any(t == p or t.startswith(p + " ") for p in SMALL_TALK)


def pick_tools(text):
    """Names of the tools worth showing the brain for this sentence. Empty means plain conversation."""
    if small_talk(text):
        return []
    words = re.findall(r"[a-z0-9]+", str(text).lower())
    if len(words) <= 6 and brain.RECENT:
        # a short answer such as "seven pm" belongs to the sentence before it
        words += re.findall(r"[a-z0-9]+", brain.RECENT[-1].lower())
    score = {}
    for name, trig in TRIGGERS.items():
        if name not in TOOLS:
            continue
        hits = sum(1 for t in trig.split() if any(w == t or (len(t) > 4 and w.startswith(t)) for w in words))
        if hits:
            score[name] = hits
    if not score:
        return []
    last = brain.LAST_ACTION[0]
    if last in TOOLS:
        score.setdefault(last, 1)
    always = [n for n in sorted(ALWAYS) if n in TOOLS]
    ranked = [n for n in sorted(score, key=lambda n: -score[n]) if n not in always][:MAX_TOOLS - len(always)]
    return ranked + always


def _short(doc):
    return doc if len(doc) <= MAX_DOC else doc[:MAX_DOC].rsplit(" ", 1)[0]


def prompt(names):
    lines = ["- " + _short(TOOLS[n]["doc"]) for n in names]
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
    pref = config.get("BROWSER") or config.get("JARVIS_BROWSER") or "google-chrome"
    _launch([pref, url] if shutil.which(pref) else ["xdg-open", url])


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
@tool("time_date", 'args {"what": "time or date"} - say the current time or date')
def time_date(args):
    now = datetime.now()
    if str(args.get("what", "time")).lower().startswith("date"):
        return f"Today is {now.strftime('%A')}, {now.day} {now.strftime('%B %Y')}."
    return f"It is {now.strftime('%I:%M %p').lstrip('0')}."


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
@tool("set_reminder", 'args {"task": "<short phrase>", "when": "YYYY-MM-DD HH:MM"} in 24-hour local time; for in ten minutes use "in_seconds": <number> instead of when; for a repeating one add "every_minutes": <number>, and when or in_seconds only if the user said when it starts')
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


# ---------- memory ----------
@tool("remember", 'args {"fact": "short statement", "key": "<two word label>"} - keep a lasting fact about the user for later; never the user\'s own name. A relative\'s or friend\'s name is fine, say who they are')
def remember(args):
    kind, message = memory.remember(args.get("fact"), args.get("key") or "")
    if kind == "reject" and not str(args.get("fact") or "").strip():
        raise ToolError(message)
    return message


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
from . import (apps, briefing, clipwatch, coder, debug, documents, guard_tools, handoff, mail, media, messaging,  # noqa: E402,F401
               notes, palette_tools, play, proactive_tools, recall, reminder_tools, screen, translate, voice_tools, watches)
from ..research import research, topic  # noqa: E402,F401
