"""Installed apps and common folders, found by name."""
import difflib
import re
import shutil
import subprocess
import time
from pathlib import Path

from ..core import config
from . import windows
from .tools import HOME, ToolError, _launch, tool

APP_DIRS = [HOME / ".local/share/applications", Path("/usr/share/applications"),
            HOME / ".local/share/flatpak/exports/share/applications",
            Path("/var/lib/flatpak/exports/share/applications")]
_apps = {"t": 0.0, "items": []}
_FILLER = {"the", "my", "app", "application", "web", "please"}
FOLDERS = {"home": HOME, "downloads": HOME / "Downloads", "documents": HOME / "Documents",
           "pictures": HOME / "Pictures", "videos": HOME / "Videos", "music": HOME / "Music",
           "desktop": HOME / "Desktop", "projects": config.PROJECTS}


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


ALIASES = {"browser": ["Google Chrome", "Firefox", "Chromium", "Brave", "Zen Browser"],
           "web browser": ["Google Chrome", "Firefox", "Chromium", "Brave"],
           "terminal": ["Konsole", "Terminal", "Alacritty", "Kitty"],
           "vs code": ["Visual Studio Code", "Code - OSS", "VSCodium"], "vscode": ["Visual Studio Code", "Code - OSS"],
           "code": ["Visual Studio Code", "Code - OSS"], "code editor": ["Visual Studio Code", "Kate"],
           "files": ["Dolphin"], "file manager": ["Dolphin"], "text editor": ["Kate", "KWrite"]}


def find_app(spoken):
    s = _norm(spoken)
    if not s:
        return None
    if s in ALIASES:
        wanted = config.get("BROWSER") if "browser" in s else ""
        for name in ([wanted] if wanted else []) + ALIASES[s]:
            hit = find_app(name) if _norm(name) not in ALIASES else None
            if hit:
                return hit
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


def _patterns(label, path):
    stem = Path(path).stem.split(".")[-1].lower()
    return [stem, re.sub(r"[^a-z0-9]", "", label.lower())]


THIS_WINDOW = ("", "this", "it", "that", "this window", "the window", "current", "the current", "current window", "the current window",
               "active", "active window", "focused", "focused window")


def _app_windows(name):
    found = find_app(name)
    if found is None:
        raise ToolError(f"I could not find an app called {name or 'that'} on this laptop.")
    label, path = found
    return label, windows.find_ids(_patterns(label, path))


def _describe_close(args):
    name = str(args.get("name", "")).strip().lower()
    if name in THIS_WINDOW:
        win = windows.active_window(max_age=0)
        title = (win[1] if win and win[1] else win[0] if win else "").strip()
        return f"Close {title[:60]}?" if title else "Close the current window?"
    label, ids = _app_windows(name)
    if not ids:
        raise ToolError(f"{label} does not seem to be open.")
    return f"Close {label}?"


@tool("close_app", 'args {"name": "<app name, or this for the current window>"} - close an open app window; for "close Spotify", "close this"',
      risk="confirm", describe=_describe_close)
def close_app(args):
    name = str(args.get("name", "")).strip().lower()
    if name in THIS_WINDOW:
        windows.close_active()
        return "Closed it."
    label, ids = _app_windows(name)
    windows.close(ids)
    return f"Closed {label}."


@tool("switch_app", 'args {"name": "<app name>"} - bring an open app to the front; for "switch to Chrome"')
def switch_app(args):
    name = str(args.get("name", "")).strip()
    label, ids = _app_windows(name)
    if not ids:
        raise ToolError(f"{label} is not open.")
    windows.activate(ids[0])
    return f"Switched to {label}."


@tool("minimise_window", 'args {} - minimise the current window; for "minimise this"')
def minimise_window(args):
    if not shutil.which("kdotool"):
        raise ToolError("I need kdotool to minimise windows.")
    windows.minimise_active()
    return "Minimised."


@tool("open_path", 'args {"name": "<folder or file name as said>"} - open a folder or a file with its default app; for "open the resume pdf", "open my downloads folder"')
def open_path(args):
    given = str(args.get("path") or "").strip()
    name = str(args.get("name", "")).strip()
    if not given:
        key = re.sub(r"^(?:the |my )|(?: folder)$", "", name.lower()).strip()
        if key in FOLDERS:
            return open_folder({"name": key})
        from .documents import locate
        given = str(locate(name, ("open_path", {})))
    _launch(["xdg-open", given])
    return f"Opening {Path(given).name}."


def _brightness_cmd(text):
    t = text.lower()
    n = re.search(r"\b(\d{1,3})\b", t)
    step = n.group(1) if n else "10"
    if re.search(r"\b(up|increase|raise|brighter)\b", t):
        return ["brightnessctl", "set", f"{step}%+"]
    if re.search(r"\b(down|decrease|lower|reduce|dim|dimmer)\b", t):
        return ["brightnessctl", "set", f"{step}%-"]
    if n and re.search(r"\bto\b|\bset\b", t):
        return ["brightnessctl", "set", f"{min(int(step), 100)}%"]
    return None


@tool("brightness", 'args {"text": "<what was said, such as brightness up or set brightness to 40>"} - change the screen brightness')
def brightness(args):
    cmd = _brightness_cmd(str(args.get("text", "")))
    if cmd is None:
        raise ToolError("Say brightness up, brightness down, or set brightness to a number.")
    if not shutil.which("brightnessctl"):
        raise ToolError("I need brightnessctl for that. Install it with dnf and try again.")
    r = subprocess.run(cmd, capture_output=True, timeout=5)
    if r.returncode:
        raise ToolError("I could not change the brightness.")
    return "Done."


@tool("open_site", 'args {"site": "<website as said, for example github.com or youtube>"} - open a website the user named in the browser')
def open_site(args):
    from .tools import _browser, heard_recently
    site = re.sub(r"\s+dot\s+", ".", str(args.get("site", "")).strip().lower()).replace(" ", "")
    site = re.sub(r"^https?://|^www\.|/.*$", "", site)
    if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)*", site) or not heard_recently(site.split(".")[0]):
        raise ToolError("Which website should I open?")
    _browser("https://" + (site if "." in site else site + ".com"))
    return f"Opening {site}."
