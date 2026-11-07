"""Reading documents: find a file, summarise it, answer questions about it, read short text aloud."""
import re
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

from ..brain import brain
from . import events, files
from ..voice.speech import Full
from .tools import ToolError, tool

CHUNK = 2500
ANSWER_CHUNK = 1500
FIRST_CHUNKS = 6
SHORT_AFTER = 3500
READ_ALOUD_MAX = 1500
MAX_PAGES = 40
_text_cache = {}
_last_summary = {"title": "", "text": ""}


def _pdfminer(path):
    try:
        from pdfminer.high_level import extract_text
    except ImportError as e:
        print(f"  (pdfminer could not be imported: {e})")
        return None
    try:
        return extract_text(str(path), maxpages=MAX_PAGES)
    except Exception as e:
        print(f"  (pdfminer failed on {path.name}: {type(e).__name__}: {e})")
        return None


def _pdftotext(path):
    if not shutil.which("pdftotext"):
        return None
    try:
        r = subprocess.run(["pdftotext", "-l", str(MAX_PAGES), "-layout", str(path), "-"],
                           capture_output=True, timeout=30)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"  (pdftotext failed: {e})")
        return None
    return r.stdout.decode(errors="replace") if r.returncode == 0 else None


def _docx(path):
    try:
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    except ImportError:
        pass
    except Exception as e:
        print(f"  (python-docx failed: {type(e).__name__}: {e})")
    try:
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode(errors="replace")
    except (OSError, KeyError, zipfile.BadZipFile) as e:
        print(f"  (could not open the Word file: {e})")
        return None
    xml = re.sub(r"</w:p>", "\n", xml)
    return re.sub(r"<[^>]+>", "", xml)


def extract(path):
    """Plain text of a PDF, text, markdown or Word file, cached until the file changes."""
    path = Path(path)
    stamp = (path.stat().st_mtime, path.stat().st_size)
    hit = _text_cache.get(path)
    if hit and hit[0] == stamp:
        return hit[1]
    kind = path.suffix.lower()
    if kind == ".pdf":
        text = _pdfminer(path) or _pdftotext(path)
    elif kind == ".docx":
        text = _docx(path)
    elif kind in (".txt", ".md", ".csv", ".log", ".rtf"):
        try:
            text = path.read_text(errors="replace")
        except OSError as e:
            print(f"  (could not read {path.name}: {e})")
            text = None
    else:
        raise ToolError(f"I can read PDF, text, markdown and Word files, but not {kind or 'that kind of file'}.")
    text = " ".join((text or "").split())
    if not text:
        raise ToolError(f"I could not get any text out of {path.name}. It may be a scanned image.")
    _text_cache.clear()
    _text_cache[path] = (stamp, text)
    return text


def chunks(text, size=CHUNK):
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = max(text.rfind(". ", i, j), text.rfind(" ", i, j))
            j = cut + 1 if cut > i + size // 2 else j
        out.append(text[i:j].strip())
        i = j
    return [c for c in out if c]


def locate(raw, then):
    try:
        return files.locate(raw, then)
    except files.FileChoice as e:
        brain.note_reply(str(e))
        raise ToolError(str(e))
    except LookupError as e:
        raise ToolError(str(e))


def _bullets(text):
    lines = [re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", ln).strip() for ln in text.splitlines()]
    return [re.sub(r"[*#`_]+", "", ln).strip() for ln in lines if len(ln.strip()) > 3][:5]


def summarise_text(text):
    parts = chunks(text)
    if len(text) <= SHORT_AFTER:
        reply = brain.ask("Summarise this in exactly 5 short bullet points:\n" + text, 300)
    else:
        picked = parts[:FIRST_CHUNKS] + ([parts[-1]] if len(parts) > FIRST_CHUNKS else [])
        notes = []
        for part in picked:
            one = brain.ask("Summarise this part of a document in two short sentences:\n" + part, 100)
            if one:
                notes.append(one)
        if not notes:
            return []
        reply = brain.ask("These are summaries of parts of one document. Combine them into exactly 5 short "
                          "bullet points:\n" + "\n".join(notes), 300)
    return _bullets(reply)


@tool("find_file", 'args {"query": "<the file name as said, with a folder if given>"} - find a file by its name; for "find my X file"')
def find_file(args):
    query = str(args.get("query") or args.get("path") or "").strip()
    path = locate(query, ("summarise_file", {}))
    return f"Found {path.name} in {path.parent.name}."


@tool("summarise_file", 'args {"path": "<file name as said, or empty for the last file>"} - read a PDF, text or Word file and speak a short summary; for "summarise this PDF", "what does this document say"')
def summarise_file(args):
    path = locate(args.get("path"), ("summarise_file", {}))
    text = extract(path)
    bullets = summarise_text(text)
    if not bullets:
        raise ToolError("I could not summarise that file right now. Try again in a minute.")
    full = "\n".join("- " + b for b in bullets)
    print(f"\nSummary of {path.name}:\n{full}\n")
    events.emit("sys", f"Summary of {path.name}:\n{full}")
    _last_summary.update(title=short_title(path), text=" ".join(bullets))
    _offer_note(path)
    return " ".join(b.rstrip(".") + "." for b in bullets) + " Want me to save this as a note?"


def short_title(path):
    return files.short_name(path) or "file"


def _offer_note(path):
    from ..core import main as core
    core.PENDING.clear()
    core.PENDING.update({"action": "take_note", "args": {"topic": short_title(path), "text": _last_summary["text"]},
                         "until": time.time() + 60})


def _words(text):
    return {w for w in re.findall(r"[a-z0-9]{3,}", text.lower())} - files.NOISE - {"what", "does", "say", "about"}


@tool("ask_about_file", 'args {"question": "<what to find out>", "path": "<file name, or empty for the last file>"} - answer a question from inside a document; for "what does it say about X"')
def ask_about_file(args):
    question = str(args.get("question") or "").strip()
    if not question:
        raise ToolError("What do you want to know about the file?")
    path = locate(args.get("path"), ("ask_about_file", {"question": question}))
    parts = chunks(extract(path), ANSWER_CHUNK)
    asked = _words(question)
    ranked = sorted(parts, key=lambda c: -len(asked & _words(c)))[:2]
    if not asked & _words(" ".join(ranked)):
        return f"I could not find anything about that in {path.name}."
    reply = brain.ask(f"Answer using only this text. If the answer is not there, say so. Question: {question}\n---\n"
                      + "\n---\n".join(ranked), 250)
    if not reply:
        raise ToolError("I could not answer that right now.")
    return " ".join(re.sub(r"[*#`]+", "", reply).split())


@tool("read_aloud_file", 'args {"path": "<file name, or empty for the last file>"} - read a short text file out loud')
def read_aloud_file(args):
    path = locate(args.get("path"), ("read_aloud_file", {}))
    if path.suffix.lower() not in (".txt", ".md", ".log", ".csv"):
        raise ToolError("I only read short text files aloud. For a PDF I can summarise it.")
    text = extract(path)
    if len(text) > READ_ALOUD_MAX:
        raise ToolError("That file is long. I can summarise it instead.")
    return Full(text)
