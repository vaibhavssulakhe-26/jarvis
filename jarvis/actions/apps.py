"""Installed apps and common folders, found by name."""
import difflib
import re
import shutil
import time
from pathlib import Path

from ..core import config
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
