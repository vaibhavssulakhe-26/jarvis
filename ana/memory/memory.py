"""What Ana remembers about the user between sessions."""
import json
import re
import threading
from datetime import datetime
from pathlib import Path

from ..core import config

FILE = Path(config.get("MEMORY_FILE", "data/memory.json")).expanduser()
if not FILE.is_absolute():
    FILE = config.ROOT / FILE
MAX_FACTS = 50
_lock = threading.Lock()


def _load():
    try:
        data = json.loads(FILE.read_text())
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    facts = [str(f) for f in data.get("facts", []) if str(f).strip()]
    return {"facts": facts[-MAX_FACTS:]}


def _save(data):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(FILE)


def remember(fact=""):
    fact = str(fact or "").strip()
    with _lock:
        data = _load()
        if fact and fact.lower() not in (f.lower() for f in data["facts"]):
            data["facts"].append(fact)
            del data["facts"][:-MAX_FACTS]
        _save(data)


def _words(text):
    return set(re.findall(r"[a-z0-9]{3,}", str(text).lower()))


def relevant(text, limit=8):
    data = _load()
    asked = _words(text)
    ranked = sorted(enumerate(data["facts"]), key=lambda p: (-len(asked & _words(p[1])), -p[0]))
    return config.PET_NAME, [fact for _, fact in ranked[:limit]]


def context(text):
    name, facts = relevant(text)
    lines = []
    if name:
        lines.append("Always address the user as " + name + ". Never adopt a different name from conversation.")
    if facts:
        lines.append("Things you remember about the user from earlier conversations:\n"
                     + "\n".join("- " + f for f in facts))
    return "\n".join(lines)


NOTES_DIR = config.ROOT / "data" / "notes"


def _slug(topic):
    return re.sub(r"[^a-z0-9]+", "-", str(topic).lower()).strip("-")[:40] or "general"


def save_note(topic, content):
    content = str(content or "").strip()
    if not content:
        raise ValueError("empty note")
    NOTES_DIR.mkdir(parents=True, exist_ok=True)
    path = NOTES_DIR / (_slug(topic) + ".txt")
    with _lock, open(path, "a") as f:
        f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M')}] {content[:2000]}\n")
    return path


def read_notes(topic):
    """Note lines whose file name or text matches the topic, newest file first. Empty list if none."""
    asked = _words(topic)
    if not asked or not NOTES_DIR.is_dir():
        return []
    files = sorted(NOTES_DIR.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    lines = []
    for path in files:
        by_name = _slug(topic) == path.stem or asked & _words(path.stem.replace("-", " "))
        for ln in path.read_text().splitlines():
            body = ln.split("] ", 1)[-1]
            if ln.strip() and (by_name or asked & _words(body)):
                lines.append(body)
    return lines
