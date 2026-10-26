"""Everything Ana can do. Each tool is one small function with a risk level."""
import difflib
import json
import re
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

from . import brain, config, reminders, voice

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


# ---------- apps and folders ----------
APP_DIRS = [HOME / ".local/share/applications", Path("/usr/share/applications"),
            HOME / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications")]
_apps = {"t": 0.0, "items": []}
_FILLER = {"the", "my", "app", "application", "web", "please"}
FOLDERS = {"home": HOME, "downloads": HOME / "Downloads", "documents": HOME / "Documents",
           "pictures": HOME / "Pictures", "videos": HOME / "Videos", "music": HOME / "Music",
           "desktop": HOME / "Desktop", "projects": HOME / "ana-projects"}


def _norm(s):
    words = re.sub(r"[^a-z0-9 ]", " ", str(s).lower()).split()
    return " ".join(w for w in words if w not in _FILLER)


def app_list():
    if time.time() - _apps["t"] < 120 and _apps["items"]:
        return _apps["items"]
    items, seen = [], set()
    for d in APP_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.desktop")):
            if f.name in seen:
                continue
            try:
                text = f.read_text(errors="ignore")
            except OSError:
                continue
            name, hidden, kind = None, False, ""
            for line in text.splitlines():
                if line.startswith("[") and not line.startswith("[Desktop Entry]"):
                    break
                if line.startswith("Name=") and name is None:
                    name = line[5:].strip()
                elif line.startswith("NoDisplay=") and line[10:].strip().lower() == "true":
                    hidden = True
                elif line.startswith("Type="):
                    kind = line[5:].strip()
            if name and not hidden and kind in ("", "Application"):
                seen.add(f.name)
                items.append((name, str(f)))
    _apps["t"], _apps["items"] = time.time(), items
    return items


def find_app(spoken):
    s = _norm(spoken)
    if not s:
        return None
    items = app_list()
    for name, path in items:
        if _norm(name) == s:
            return name, path
    stoks = set(s.split())
    best, best_score = None, 0.0
    for name, path in items:
        n = _norm(name)
        ntoks = set(n.split())
        score = difflib.SequenceMatcher(None, s, n).ratio()
        if stoks and stoks <= ntoks and len(ntoks) <= len(stoks) + 1:
            score = max(score, 0.85)
        if score > best_score:
            best, best_score = (name, path), score
    return best if best_score >= 0.78 else None


@tool("open_app", 'args {"name": "<app name as said, for example Chrome, YouTube Music, Instagram, WhatsApp>"} - open an installed app or web app')
def open_app(args):
    name = str(args.get("name", "")).strip()
    found = find_app(name)
    if found is None:
        raise ToolError(f"I could not find an app called {name or 'that'} on this laptop.")
    label, path = found
    if shutil.which("gio"):
        _launch(["gio", "launch", path])
    elif shutil.which("gtk-launch"):
        _launch(["gtk-launch", Path(path).stem])
    else:
        raise ToolError("I cannot launch apps because gio is missing.")
    return f"Opening {label}."


@tool("open_folder", 'args {"name": "<home, downloads, documents, pictures, videos, music, desktop or projects>"}')
def open_folder(args):
    name = str(args.get("name", "")).lower().strip()
    path = FOLDERS.get(name)
    if path is None or not path.exists():
        raise ToolError("I can open: " + ", ".join(FOLDERS) + ".")
    _launch(["dolphin", str(path)])
    return f"Opening {name}."


# ---------- system ----------
@tool("battery", "args {} - tell the battery level")
def battery(args):
    for d in sorted(Path("/sys/class/power_supply").glob("BAT*")):
        try:
            pct = (d / "capacity").read_text().strip()
            status = (d / "status").read_text().strip().lower()
        except OSError:
            continue
        return f"Battery is at {pct} percent and {status}."
    raise ToolError("I could not read the battery.")


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


@tool("media", 'args {"do": "play_pause, play, pause, next or previous"} - control the music player')
def media(args):
    cmds = {"play_pause": "play-pause", "play": "play", "pause": "pause", "next": "next", "previous": "previous"}
    cmd = cmds.get(str(args.get("do", "")).lower().strip())
    if cmd is None:
        raise ToolError("I can play, pause, skip or go back.")
    if shutil.which("playerctl") is None:
        raise ToolError("Media control needs playerctl. Install it with: sudo dnf install playerctl")
    subprocess.run(["playerctl", cmd], timeout=5)
    return "Done."


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


# ---------- web and music ----------
@tool("web_search", 'args {"query": "..."} - open a web search in the browser')
def web_search(args):
    q = str(args.get("query", "")).strip()
    if not q:
        raise ToolError("What should I search for?")
    _browser("https://duckduckgo.com/?q=" + quote(q))
    return f"Searching for {q}."


def _warm_ytdlp():
    try:
        import yt_dlp  # noqa: F401
    except Exception:
        pass


threading.Thread(target=_warm_ytdlp, daemon=True).start()


def _youtube_id(query):
    result = [""]

    def go():
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "socket_timeout": 8}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info("ytsearch1:" + query, download=False)
            for entry in (info or {}).get("entries") or []:
                vid = str((entry or {}).get("id", ""))
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                    result[0] = vid
                    return
        except Exception as e:
            print(f"  (video lookup failed: {type(e).__name__})")

    worker = threading.Thread(target=go, daemon=True)
    worker.start()
    worker.join(12)
    return result[0]


def _resume_later(delay):
    def go():
        time.sleep(delay)
        if shutil.which("playerctl"):
            try:
                subprocess.run(["playerctl", "-p", "chromium,chrome,firefox", "play"],
                               capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
    threading.Thread(target=go, daemon=True).start()


@tool("play_media", 'args {"service": "youtube_music or youtube", "query": "<song, artist or video>"} - start playing music or a video; use an empty query ONLY to resume what is already playing in an open player; if the user asks to play something unnamed such as the first video, use ask instead')
def play_media(args):
    service = str(args.get("service", "youtube_music")).lower()
    query = str(args.get("query", "")).strip()[:120]
    music = "music" in service or "youtube" not in service
    label = "YouTube Music" if music else "YouTube"
    if not query:
        found = find_app(label)
        if found and shutil.which("gio"):
            _launch(["gio", "launch", found[1]])
        else:
            _browser("https://music.youtube.com" if music else "https://www.youtube.com")
        _resume_later(9)
        return f"Opening {label}. I will try to press play for you."
    if query.lower().strip(" .") in {"music", "song", "songs", "a song", "video", "videos", "something", "anything", "some music"}:
        raise ToolError("Which song or artist should I play?")
    if not heard_recently(query):
        raise ToolError("I am not sure what you want me to play. Which song or video?")
    voice.say(f"Looking that up on {label}.")
    vid = _youtube_id(query)
    if vid:
        base = "https://music.youtube.com/watch?v=" if music else "https://www.youtube.com/watch?v="
        _browser(base + vid)
        _resume_later(7)
        return f"Playing {query} on {label}. If it does not start by itself, press play once."
    _browser(("https://music.youtube.com/search?q=" if music
              else "https://www.youtube.com/results?search_query=") + quote(query))
    return f"I opened the {label} search for {query}. I cannot press play on that page yet."


# ---------- writing and code ----------
@tool("draft_text", 'args {"title": "<2 to 4 words>", "text": "<the full draft>"} - write an email or message draft for the user to review; never sends anything')
def draft_text(args):
    text = str(args.get("text", "")).strip()
    if not text:
        raise ToolError("There was nothing to draft.")
    title = re.sub(r"[^a-z0-9]+", "-", str(args.get("title", "draft")).lower()).strip("-")[:40] or "draft"
    folder = HOME / "Documents" / "drafts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{title}.txt").write_text(text[:6000] + "\n")
    print("\n" + text + "\n")
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


# ---------- messages to saved contacts ----------
CONTACTS = config.DATA / "contacts.json"
CONTACT_ALIASES = {"mom": {"mum", "mummy", "mother", "mama", "amma", "ma"},
                   "dad": {"daddy", "father", "papa", "appa", "pa"}}


def _contacts():
    try:
        data = json.loads(CONTACTS.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _find_contact(spoken):
    name = re.sub(r"[^a-z ]", "", str(spoken).lower()).strip()
    book = _contacts()
    if name in book:
        return name, book[name]
    for key, alts in CONTACT_ALIASES.items():
        if name == key or name in alts:
            for cand in (key, *alts):
                if cand in book:
                    return cand, book[cand]
    close = difflib.get_close_matches(name, list(book), n=1, cutoff=0.8)
    if close:
        return close[0], book[close[0]]
    return None, None


def _prepare_message(args, check=True):
    name, entry = _find_contact(args.get("contact", ""))
    if not entry or not str(entry.get("phone", "")).isdigit():
        known = ", ".join(_contacts()) or "nobody yet"
        raise ToolError(f"I do not have a number saved for {args.get('contact') or 'that contact'}. "
                        f"Saved contacts: {known}.")
    text = str(args.get("text", "")).strip()[:500]
    if not text:
        raise ToolError("What should the message say?")
    if check and not heard_recently(text):
        raise ToolError(f"I did not hear what the message to {name} should say. What should I write?")
    return name, entry["phone"], text


def _describe_message(args):
    name, phone, text = _prepare_message(args)
    args["_checked"] = True
    return f"I will send {name} this on WhatsApp: {text}."


def _trusted(args):
    try:
        trusted = {x.strip().lower() for x in config.get("ANA_TRUSTED_CONTACTS").split(",") if x.strip()}
        name, entry = _find_contact(args.get("contact", ""))
        return bool(name and name in trusted and len(str(args.get("text", ""))) <= 120
                    and heard_recently(args.get("text", "")))
    except Exception:
        return False


def _press_enter():
    from evdev import UInput, ecodes as e
    ui = UInput({e.EV_KEY: [e.KEY_ENTER]}, name="ana-keyboard")
    try:
        time.sleep(0.5)
        ui.write(e.EV_KEY, e.KEY_ENTER, 1)
        ui.syn()
        time.sleep(0.05)
        ui.write(e.EV_KEY, e.KEY_ENTER, 0)
        ui.syn()
        time.sleep(0.2)
    finally:
        ui.close()


def _send_later(delay, name):
    def go():
        time.sleep(delay)
        try:
            _press_enter()
            voice.say(f"I pressed send for {name}. Take a quick look to make sure it went through.")
        except Exception as e:
            voice.say(f"I could not press send, {type(e).__name__}. You can press Enter yourself.")
    threading.Thread(target=go, daemon=True).start()


@tool("message_contact", 'args {"contact": "<name as said, for example mom>", "text": "<the message>"} - send a WhatsApp message to a saved contact; the program types it and presses send after the user confirms',
      risk="confirm", describe=_describe_message, skip=_trusted)
def message_contact(args):
    name, phone, text = _prepare_message(args, check=not args.get("_checked"))
    try:
        delay = max(5.0, min(40.0, float(config.get("ANA_SEND_DELAY", "13"))))
    except ValueError:
        delay = 13.0
    _browser(f"https://web.whatsapp.com/send?phone={phone}&text={quote(text)}")
    _send_later(delay, name)
    return f"Sending to {name}: {text}. Please keep your hands off the keyboard for a few seconds."


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
