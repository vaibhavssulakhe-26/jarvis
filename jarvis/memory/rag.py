"""Full-text search over notes and PDFs. SQLite FTS5 with BM25 ranking, no embedding model."""
import difflib
import re
import sqlite3
import threading
from pathlib import Path

from ..core import config

DB = config.DATA / "rag.db"
KINDS = (".md", ".txt", ".pdf")
CHUNK_CHARS = 700
MAX_FILES = 2000
MAX_CHARS = 400_000
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "my", "me", "i", "is", "it", "about", "what", "did",
        "do", "does", "write", "wrote", "note", "notes", "noted", "say", "said", "search", "find", "tell", "with", "that",
        "this", "have", "has", "was", "were", "are", "you", "your", "any", "all", "from", "how", "when", "where", "who"}
_lock = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS files(path TEXT PRIMARY KEY, name TEXT, mtime REAL, size INTEGER, chunks INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(text, path UNINDEXED, name UNINDEXED, pos UNINDEXED, tokenize='porter unicode61');
"""


def folders():
    """NOTES_DIR (default data/notes) plus every folder listed in RAG_FOLDERS (comma separated)."""
    first = Path(config.get("NOTES_DIR") or config.DATA / "notes").expanduser()
    extra = [Path(p.strip()).expanduser() for p in config.get("RAG_FOLDERS").split(",") if p.strip()]
    return list(dict.fromkeys([first] + extra))


def _connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def scan():
    """{path: (mtime, size)} for every indexable file under the configured folders."""
    found = {}
    for root in folders():
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if len(found) >= MAX_FILES:
                return found
            if p.suffix.lower() in KINDS and p.is_file() and not any(part.startswith(".") for part in p.relative_to(root).parts):
                st = p.stat()
                found[str(p)] = (st.st_mtime, st.st_size)
    return found


def read_text(path):
    path = Path(path)
    if path.suffix.lower() == ".pdf":
        from ..actions import documents
        return documents.extract(path)
    return path.read_text(errors="replace")


def split(text, size=CHUNK_CHARS):
    """Pieces of about size characters, cut at a paragraph, line or sentence end where there is one."""
    text = re.sub(r"[ \t]+", " ", text).strip()[:MAX_CHARS]
    out, i = [], 0
    while i < len(text):
        j = min(len(text), i + size)
        if j < len(text):
            cut = max(text.rfind("\n\n", i, j), text.rfind("\n", i, j), text.rfind(". ", i, j))
            if cut > i + size // 2:
                j = cut + 1
        piece = " ".join(text[i:j].split())
        if piece:
            out.append(piece)
        i = j
    return out


def changed():
    """True when a file was added, edited or removed since the last index."""
    now = scan()
    with _lock, _connect() as con:
        old = {r["path"]: (r["mtime"], r["size"]) for r in con.execute("SELECT path, mtime, size FROM files")}
    return {k: v for k, v in now.items()} != old


def reindex(force=False):
    """Bring the index up to date. Returns (indexed, removed); unreadable files are skipped, not fatal."""
    now = scan()
    indexed = removed = 0
    with _lock:
        con = _connect()
        try:
            old = {r["path"]: (r["mtime"], r["size"]) for r in con.execute("SELECT path, mtime, size FROM files")}
            for path in set(old) - set(now):
                con.execute("DELETE FROM chunks WHERE path=?", (path,))
                con.execute("DELETE FROM files WHERE path=?", (path,))
                removed += 1
            for path, stamp in now.items():
                if not force and old.get(path) == stamp:
                    continue
                try:
                    pieces = split(read_text(path))
                except Exception as e:
                    print(f"  (could not index {Path(path).name}: {type(e).__name__})")
                    pieces = []
                name = Path(path).name
                con.execute("DELETE FROM chunks WHERE path=?", (path,))
                con.executemany("INSERT INTO chunks(text, path, name, pos) VALUES(?, ?, ?, ?)",
                                [(p, path, name, n) for n, p in enumerate(pieces)])
                con.execute("INSERT OR REPLACE INTO files(path, name, mtime, size, chunks) VALUES(?, ?, ?, ?, ?)",
                            (path, name, stamp[0], stamp[1], len(pieces)))
                indexed += 1
            con.commit()
        finally:
            con.close()
    return indexed, removed


def update_if_changed():
    if changed():
        return reindex()
    return 0, 0


def start():
    """At startup, reindex in the background but only when files changed."""
    def go():
        try:
            done, gone = update_if_changed()
            if done or gone:
                print(f"  (notes index: {done} updated, {gone} removed)")
        except Exception as e:
            print(f"  (notes index failed: {type(e).__name__})")
    threading.Thread(target=go, daemon=True).start()


def terms(query):
    words = [w for w in re.findall(r"[a-z0-9]+", str(query).lower()) if w not in STOP and len(w) > 1]
    return list(dict.fromkeys(words))


def search(query, k=3):
    """The k best chunks as dicts with name, path and text. Empty when nothing matches."""
    words = terms(query)
    if not words:
        return []
    match = " OR ".join('"' + w + '"' for w in words)
    with _lock, _connect() as con:
        try:
            rows = con.execute("SELECT name, path, text FROM chunks WHERE chunks MATCH ? ORDER BY bm25(chunks) LIMIT ?",
                               (match, k)).fetchall()
        except sqlite3.OperationalError:
            return []
    return [dict(r) for r in rows]


def count():
    with _lock, _connect() as con:
        return con.execute("SELECT COUNT(*) FROM files").fetchone()[0]


def find(name):
    """The indexed file a spoken name points at, or None. Matches on the file name without punctuation or extension."""
    want = re.sub(r"[^a-z0-9]+", " ", str(name).lower()).strip()
    want = re.sub(r"\s+(?:file|document|pdf|note|notes)$", "", want)
    if not want:
        return None
    with _lock, _connect() as con:
        rows = [(r["path"], re.sub(r"[^a-z0-9]+", " ", Path(r["path"]).stem.lower()).strip())
                for r in con.execute("SELECT path FROM files")]
    for path, stem in rows:
        if stem == want:
            return Path(path)
    contains = [p for p, stem in rows if want in stem or (len(stem) > 3 and stem in want)]
    if len(contains) == 1:
        return Path(contains[0])
    best = difflib.get_close_matches(want, [s for _, s in rows], 1, 0.8)
    return next((Path(p) for p, s in rows if best and s == best[0]), None)


def last_indexed():
    """When the index file was last written, or None if there is no index yet."""
    try:
        return DB.stat().st_mtime
    except OSError:
        return None
