"""Read-only file tools: list a folder, open a file, read a text file, describe an image. Everything stays inside the home folder and
nothing on the deny list (core/access.py, FILE_DENY) is listed, read or opened. "The 4th picture in Pictures" is turned into a sorted
list first and the file is named in a yes or no question before anything happens."""
import re
from pathlib import Path

from .. import platform
from ..brain import brain
from ..core import access, config
from . import events, files, screen
from .tools import ToolError, tool

HOME = Path.home()
PICTURES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
DOCS = {".pdf", ".txt", ".md", ".docx", ".odt", ".rtf", ".doc"}
TEXT = {".txt", ".md", ".py", ".json", ".csv", ".log", ".html", ".css", ".js", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".tex", ".xml"}
KINDS = {"picture": PICTURES, "pictures": PICTURES, "image": PICTURES, "images": PICTURES, "photo": PICTURES, "photos": PICTURES,
         "document": DOCS, "documents": DOCS, "doc": DOCS, "docs": DOCS, "pdf": {".pdf"}, "pdfs": {".pdf"}, "text": TEXT}
ORD = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "last": -1}
SPOKEN = 6
READ_CHARS = 3000
IMAGE_PROMPT = 'Describe this image in at most three short sentences. Reply with exactly one JSON object: {"say": "..."}'
LAST = {"folder": None, "items": []}


def folder_of(name):
    """The folder a spoken name or path points at, inside the home folder."""
    raw = str(name or "").strip()
    if not raw:
        return HOME
    key = re.sub(r"^(?:the |my )|(?: folder| directory)$", "", raw.lower()).strip()
    if key in files.HINTS:
        found = HOME / files.HINTS[key]
    else:
        found = Path(raw).expanduser()
        if not found.is_absolute():
            found = HOME / raw
    if not access.readable(found) or not found.is_dir():
        raise ToolError(f"I cannot list {raw[:40]}. It is not a folder in your home folder, or it is off limits.")
    return found


def listing(folder, kind="", sort="name"):
    """The visible, allowed entries of a folder: folders first for name order, newest first for date order."""
    exts = KINDS.get(str(kind).lower().strip())
    out = []
    for p in folder.iterdir():
        if p.name.startswith(".") or access.denied(p) or not access.readable(p):
            continue
        if exts is not None and (not p.is_file() or p.suffix.lower() not in exts):
            continue
        out.append(p)
    if str(sort).lower().startswith("date"):
        return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)
    return sorted(out, key=lambda p: (not p.is_dir(), p.name.lower()))


@tool("list_folder", 'args {"folder": "<folder name or path>", "sort": "name or date", "kind": "pictures, documents, pdf or empty for everything"} - list what is in a folder; for "what is in my downloads", "list my pictures by date"')
def list_folder(args):
    folder = folder_of(args.get("folder"))
    items = listing(folder, args.get("kind"), args.get("sort") or "name")
    LAST.update(folder=folder, items=items)
    if not items:
        return f"{folder.name} has nothing{' of that kind' if args.get('kind') else ''}."
    text = "\n".join(f"{i}. {p.name}{'/' if p.is_dir() else ''}" for i, p in enumerate(items, 1))
    print(text)
    events.emit("sys", f"{folder}\n{text}")
    by = "newest first" if str(args.get("sort") or "").lower().startswith("date") else "by name"
    names = ", ".join(p.name for p in items[:SPOKEN])
    return f"{folder.name} has {len(items)} item{'s' if len(items) != 1 else ''}. First {min(SPOKEN, len(items))} {by}: {names}."


def _index(value):
    word = str(value or "").strip().lower().rstrip(".")
    if word in ORD:
        return ORD[word]
    m = re.match(r"^(-?\d+)(?:st|nd|rd|th)?$", word)
    return int(m.group(1)) if m else None


def resolve(args):
    """(path, by_position). A path wins; otherwise the folder, kind, sort and position give one file of the sorted list."""
    given = str(args.get("path") or "").strip()
    if given:
        path = Path(given).expanduser()
        if not path.is_absolute():
            path = (Path(args["folder"]).expanduser() if args.get("folder") else HOME) / given
        if not access.readable(path) or not path.exists():
            raise ToolError("I cannot open that. It is missing, outside your home folder or off limits.")
        return path, False
    n = _index(args.get("index"))
    if n is None or n == 0:
        raise ToolError("Which one? Give me a file name, or a number in a folder.")
    items = [p for p in listing(folder_of(args.get("folder")), args.get("kind"), args.get("sort") or "name") if p.is_file()]
    if not items or abs(n) > len(items):
        raise ToolError(f"There are only {len(items)} matching files there.")
    return items[n - 1 if n > 0 else n], True


def _ask(verb):
    def describe(args):
        path, _ = resolve(args)
        place = f" in {Path(path).parent.name}" if args.get("index") else ""
        return f"Number {args.get('index')}{place}, sorted by {args.get('sort') or 'name'}, is {path.name}. {verb} it?"
    return describe


def _by_position(args):
    return not args.get("index")


@tool("open_file", 'args {"path": "<file>", "folder": "<folder>", "index": "<position such as 4 or fourth>", "kind": "pictures or documents", "sort": "name or date"} - open one file with its default app; a position is confirmed first; for "open the 4th picture in my pictures"',
      risk="confirm", describe=_ask("Open"), skip=_by_position)
def open_file(args):
    path, _ = resolve(args)
    if path.is_dir():
        raise ToolError("That is a folder. Use the folder tools for it.")
    platform.open_target(str(path))
    return f"Opening {path.name}."


@tool("read_text_file", 'args {"path": "<file>", "folder": "<folder>", "index": "<position>", "kind": "documents"} - read the start of a text, markdown, code or PDF file; for "read notes.txt"',
      risk="confirm", describe=_ask("Read"), skip=_by_position)
def read_text_file(args):
    path, _ = resolve(args)
    if path.suffix.lower() in (".pdf", ".docx", ".odt", ".rtf"):
        from .documents import extract
        return extract(path)[:READ_CHARS]
    if path.suffix.lower() not in TEXT or not path.is_file():
        raise ToolError(f"I can read text files, not {path.suffix or 'that kind of file'}.")
    return path.read_text(encoding="utf-8", errors="replace")[:READ_CHARS]


@tool("describe_image", 'args {"path": "<image>", "folder": "<folder>", "index": "<position>", "kind": "pictures"} - say what is in a picture, with the vision model when GROQ_VISION_MODEL is set, otherwise the text found by OCR; for "what is in the 4th picture"',
      risk="confirm", describe=_ask("Look at"), skip=_by_position)
def describe_image(args):
    path, _ = resolve(args)
    if path.suffix.lower() not in PICTURES:
        raise ToolError("That is not a picture file.")
    if config.get("GROQ_VISION_MODEL") and not config.offline():
        try:
            data = brain.look(IMAGE_PROMPT, screen._jpeg(path))
        except ToolError:
            data = None
        say = str((data or {}).get("say", "")).strip()
        if say:
            return say
        note = "The vision model did not answer, so this is the text I could read: "
    else:
        note = "No vision model is available, so this is the text I could read: "
    text = screen.clean_ocr(screen.ocr_text(path))
    if not text.strip():
        raise ToolError(f"I found no text in {path.name} and no vision model answered.")
    return note + text[:400]
