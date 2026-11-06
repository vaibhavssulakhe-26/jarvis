"""Finding files by a spoken name. Forgiving about case, separators, missing words and mishearings."""
import difflib
import os
import re
import time
from datetime import datetime
from pathlib import Path

HOME = Path.home()
STANDARD = ("Downloads", "Documents", "Desktop", "Pictures")
HINTS = {"downloads": "Downloads", "download": "Downloads", "desktop": "Desktop", "documents": "Documents",
         "docs": "Documents", "pictures": "Pictures", "photos": "Pictures", "whatsapp": "WhatsApp", "home": ""}
SKIP_NAMES = {"node_modules", "venv", "env", "site-packages", "__pycache__", "snap", "flatpak"}
SKIP_PATHS = ("/.local/share", "/.cache")
NOISE = {"the", "a", "an", "my", "of", "in", "on", "from", "inside", "folder", "file", "please", "it", "that",
         "this", "for", "and", "named", "called", "me", "summarise", "summarize", "summary", "read", "open",
         "find", "document", "doc", "pdf", "text", "word", "about", "what", "does", "say", "is", "there"}
DOC_KINDS = {".pdf", ".txt", ".md", ".docx", ".doc", ".odt", ".rtf"}
ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3,
            "fifth": 4, "5th": 4}
COUNTS = {"one": 0, "two": 1, "three": 2, "four": 3, "five": 4, "1": 0, "2": 1, "3": 2, "4": 3, "5": 4}
MAX_ENTRIES = 40000
MAX_SECONDS = 8.0
CLEAR_GAP = 0.15
SESSION = {"results": [], "last": None}
PENDING = {}


class FileChoice(Exception):
    """Several files fit; the message is the question to ask."""


NUMBERS = {"zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
           "seven": "7", "eight": "8", "nine": "9", "ten": "10"}


def _tokens(text):
    spaced = re.sub(r"([a-z])([A-Z])", r"\1 \2", str(text))
    return [NUMBERS.get(t, t) for t in re.findall(r"[a-z0-9]+", spaced.lower())]


def split_query(query):
    """(folder hint or None, words, preferred extensions) from a spoken file description."""
    q = str(query).lower()
    hint = None
    m = re.search(r"\b(?:in|from|on|inside|under)\s+(?:my |the )?(downloads?|desktop|documents|docs|pictures|photos|whatsapp|home)\b", q)
    if m:
        hint = HINTS[m.group(1)]
        q = q.replace(m.group(0), " ")
    prefer = set()
    if re.search(r"\bpdf\b", q):
        prefer = {".pdf"}
    elif re.search(r"\b(document|doc|docs|text|notes?)\b", q):
        prefer = DOC_KINDS
    elif re.search(r"\bword\b", q):
        prefer = {".docx", ".doc"}
    words = [w for w in _tokens(q) if w not in NOISE and len(w) > 1]
    return hint, words, prefer


def _hint_dirs(hint):
    if hint is None:
        return []
    if hint == "":
        return [HOME]
    if hint == "WhatsApp":
        found = [p for p in (HOME / "Downloads" / "WhatsApp", HOME / "Documents" / "WhatsApp",
                             HOME / "Pictures" / "WhatsApp", HOME / "WhatsApp") if p.is_dir()]
        for p in _walk_dirs(HOME, 4):
            if "whatsapp" in p.name.lower() and p not in found:
                found.append(p)
        return found
    return [HOME / hint] if (HOME / hint).is_dir() else []


def _walk_dirs(base, depth):
    stack = [(base, 0)]
    while stack:
        d, level = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            if e.is_dir(follow_symlinks=False) and not _skip_dir(e):
                yield Path(e.path)
                if level + 1 < depth:
                    stack.append((Path(e.path), level + 1))


def _skip_dir(entry):
    name = entry.name
    return name.startswith(".") or name.lower() in SKIP_NAMES or any(entry.path.endswith(s) for s in SKIP_PATHS)


def _files_under(base, depth, budget):
    """Yield files under base down to depth, skipping hidden and dependency folders. budget is a shared counter."""
    stack = [(str(base), 0)]
    while stack:
        d, level = stack.pop()
        try:
            entries = list(os.scandir(d))
        except OSError:
            continue
        for e in entries:
            budget["n"] += 1
            if budget["n"] > MAX_ENTRIES or time.time() > budget["until"]:
                return
            try:
                if e.is_dir(follow_symlinks=False):
                    if level + 1 < depth and not _skip_dir(e):
                        stack.append((e.path, level + 1))
                elif e.is_file() and not e.name.startswith("."):
                    yield e
            except OSError:
                continue


def score(words, prefer, path):
    """How well a file name fits the spoken words, 0 to about 1.1."""
    stem = Path(path).stem
    toks = _tokens(stem)
    if not words or not toks:
        return 0.0
    got = 0.0
    for w in words:
        best = 0.0
        for t in toks:
            if w == t:
                best = 1.0
                break
            if len(w) >= 3 and len(t) >= 3 and (w in t or t in w):
                best = max(best, 0.8)
            elif len(w) >= 4 and len(t) >= 4 and difflib.SequenceMatcher(None, w, t).ratio() >= 0.75:
                best = max(best, 0.7)
        got += best
    coverage = got / len(words)
    q, s = "".join(words), "".join(toks)
    sim = difflib.SequenceMatcher(None, q, s).ratio()
    if coverage < 0.5 and sim < 0.75:
        return 0.0
    total = 0.75 * coverage + 0.25 * sim + (0.2 if q == s else 0.0)
    if prefer and Path(path).suffix.lower() in prefer:
        total += 0.1
    return total


def _stages(hint):
    hinted = _hint_dirs(hint)
    if hint is not None:
        yield "hinted", hinted, 5
    standard = [HOME / d for d in STANDARD if (HOME / d).is_dir()]
    yield "standard", standard, 4
    yield "home", [HOME], 5


def find_files(query, folder_hint=None):
    """Top 5 matches as dicts with path, size, modified and score. Also remembers them for follow-ups."""
    hint, words, prefer = split_query(query)
    hint = folder_hint if folder_hint is not None else hint
    if not words:
        SESSION["results"] = []
        return []
    found = {}
    searched = []
    budget = {"n": 0, "until": time.time() + MAX_SECONDS}
    for stage, bases, depth in _stages(hint):
        for base in bases:
            searched.append(base.name or "home")
            for e in _files_under(base, depth, budget):
                if e.path in found:
                    continue
                s = score(words, prefer, e.path)
                if s:
                    st = e.stat()
                    found[e.path] = {"path": Path(e.path), "size": st.st_size, "modified": st.st_mtime, "score": s}
        best = max((r["score"] for r in found.values()), default=0)
        if best >= 0.9:
            break
    ranked = sorted(found.values(), key=lambda r: (-round(r["score"], 3), -r["modified"]))[:5]
    SESSION["results"] = ranked
    SESSION["searched"] = sorted(set(searched), key=searched.index)
    return ranked


def short_name(path):
    words = _tokens(Path(path).stem)
    return " ".join(words[:7])


def describe(results):
    names = [short_name(r["path"]) for r in results]
    out = []
    for r, n in zip(results, names):
        label = n
        if names.count(n) > 1:
            label += " in " + r["path"].parent.name
        out.append(f"{label}, {datetime.fromtimestamp(r['modified']).strftime('%d %b')}")
    return out


def where_searched():
    folders = SESSION.get("searched") or list(STANDARD)
    return ", ".join(folders[:-1]) + " and " + folders[-1] if len(folders) > 1 else folders[0]


def clear_winner(results):
    return len(results) == 1 or (len(results) > 1 and results[0]["score"] - results[1]["score"] >= CLEAR_GAP)


def close_ones(results):
    return [r for r in results if results[0]["score"] - r["score"] < CLEAR_GAP][:5]


def pick(text):
    """The remembered result a phrase such as 'the second one' or 'the newest' points at, or None."""
    options = PENDING.get("options") or SESSION["results"]
    if not options:
        return None
    t = str(text).lower()
    if re.search(r"\b(newest|latest|most recent|last modified)\b", t):
        return max(options, key=lambda r: r["modified"])
    if re.search(r"\b(oldest)\b", t):
        return min(options, key=lambda r: r["modified"])
    if re.search(r"\blast one\b", t):
        return options[-1]
    for word, i in ORDINALS.items():
        if re.search(rf"\b{word}\b", t) and i < len(options):
            return options[i]
    m = re.search(r"\b(?:number|option|file|result)\s+(one|two|three|four|five|[1-5])\b", t)
    if m and COUNTS[m.group(1)] < len(options):
        return options[COUNTS[m.group(1)]]
    return None


def is_pronoun(raw):
    return bool(re.fullmatch(r"(?:it|that|this|that file|this file|the file|the document|that one|the same one|"
                             r"the last file|last file|the pdf|that pdf|again|)", str(raw or "").strip().lower()))


def locate(raw, then=None):
    """Resolve a spoken description to one Path. then is (tool name, args) to run once the user picks an option.
    Raises FileChoice with a question when several files fit, or LookupError with a full explanation when none."""
    raw = str(raw or "").strip()
    direct = Path(raw).expanduser()
    if raw and (direct.is_absolute() or raw.startswith(("~", "./"))) and direct.is_file():
        SESSION["last"] = direct
        return direct
    if is_pronoun(raw) and SESSION["last"] and Path(SESSION["last"]).is_file():
        return Path(SESSION["last"])
    chosen = pick(raw) if raw else None
    if chosen:
        PENDING.clear()
        SESSION["last"] = chosen["path"]
        return chosen["path"]
    results = find_files(raw)
    if not results:
        raise LookupError(f"I looked in {where_searched()} and found nothing like {raw}. "
                          "Tell me more of the file name, or which folder it is in.")
    if clear_winner(results):
        SESSION["last"] = results[0]["path"]
        PENDING.clear()
        return results[0]["path"]
    near = close_ones(results)
    SESSION["results"] = near
    PENDING.update({"options": near, "then": then, "until": time.time() + 120})
    raise FileChoice(f"I found {len(near)} files: " + "; ".join(describe(near))
                     + ". Which one, the first, the second, or the newest?")


def waiting():
    if PENDING and time.time() > PENDING.get("until", 0):
        PENDING.clear()
    return bool(PENDING)


def take_choice(text):
    """If a file question is open and text answers it, return (tool name, args) to run, else None."""
    if not waiting():
        return None
    chosen = pick(text)
    if not chosen:
        return None
    then = PENDING.get("then")
    PENDING.clear()
    SESSION["last"] = chosen["path"]
    if not then:
        return None
    action, args = then
    return action, dict(args, path=str(chosen["path"]))
