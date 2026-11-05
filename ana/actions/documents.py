"""Reading a PDF or text file aloud as a short summary."""
import re
from pathlib import Path

from pdfminer.high_level import extract_text

from ..brain import brain
from .tools import HOME, ToolError, tool

MAX_CHARS = 3000
KINDS = (".pdf", ".txt")
FOLDERS = ("Downloads", "Documents", "Desktop", "WhatsApp", "Pictures")
MAX_OPTIONS = 4

def _extract(path):
    if path.suffix.lower() == ".pdf":
        return extract_text(str(path), maxpages=30)
    try:
        return path.read_text(errors="replace")
    except OSError:
        raise ToolError("I could not read that file.")


def _split_hint(query):
    """Pull a folder name such as "in downloads" out of the query; returns (folder or None, filename words)."""
    words = re.findall(r"[a-z0-9]+", query.lower())
    folder = next((f for f in FOLDERS if f.lower() in words), None)
    drop = {"in", "from", "inside", "my", "the", "folder", "file", "pdf", "document"}
    if folder:
        drop.add(folder.lower())
    return folder, [w for w in words if w not in drop]


def _candidates(folders, words):
    found = {}
    for folder in folders:
        base = HOME / folder
        if not base.is_dir():
            continue
        for pattern in ("*", "*/*"):
            for p in base.glob(pattern):
                name = p.name.lower()
                if p.is_file() and p.suffix.lower() in KINDS and not name.startswith(".") \
                        and all(w in name for w in words):
                    found[p.resolve()] = p
    return sorted(found.values(), key=lambda p: p.name.lower())


def find_file(raw):
    direct = Path(raw).expanduser()
    if direct.is_absolute() or raw.startswith(("~", "./")):
        if direct.is_file():
            return direct
    folder, words = _split_hint(raw)
    if not words:
        raise ToolError("Which file should I read?")
    hinted = folder and (HOME / folder).is_dir()
    hits = _candidates([folder] if hinted else FOLDERS, words)
    if not hits:
        raise ToolError("I could not find that file in your Downloads, Documents or Desktop.")
    if len(hits) > 1:
        exact = [p for p in hits if p.stem.lower() == " ".join(words)]
        if len(exact) == 1:
            return exact[0]
        names = [p.name for p in hits[:MAX_OPTIONS]]
        question = "I found " + str(len(hits)) + " files: " + ", ".join(names) + ". Which one do you mean?"
        brain.note_reply(question)
        raise ToolError(question)
    return hits[0]


@tool("summarise_file", 'args {"path": "<path to a PDF or .txt file>"} - read a document and speak a bullet-point summary; for "summarise this PDF", "what does this document say" or "read this file for me"')
def summarise_file(args):
    raw = str(args.get("path") or "").strip()
    if not raw:
        raise ToolError("Which file should I read?")
    path = find_file(raw)
    text = " ".join(_extract(path).split())
    if not text:
        raise ToolError("I found no text in that file.")
    reply = brain.complete(f"Summarise this in 5 bullet points: {text[:MAX_CHARS]}")
    if not reply:
        raise ToolError("I could not summarise that file right now.")
    reply = re.sub(r"[*#`]+|^\s*[-•]\s*", "", reply, flags=re.M)
    return " ".join(reply.split())
