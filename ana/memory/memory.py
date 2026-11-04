"""What Ana remembers about the user between sessions."""
import json
import re
import threading
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
    return {"name": str(data.get("name") or ""), "facts": facts[-MAX_FACTS:]}


def _save(data):
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_name(FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(FILE)


def remember(fact="", name=""):
    fact, name = str(fact or "").strip(), str(name or "").strip()
    with _lock:
        data = _load()
        if name:
            data["name"] = name
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
    return data["name"], [fact for _, fact in ranked[:limit]]


def context(text):
    name, facts = relevant(text)
    lines = []
    if name:
        lines.append("The user's name is " + name + ".")
    if facts:
        lines.append("Things you remember about the user from earlier conversations:\n"
                     + "\n".join("- " + f for f in facts))
    return "\n".join(lines)
