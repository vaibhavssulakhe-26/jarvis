"""What Jarvis may read: inside the home folder only, and never a path with a word from the deny list (FILE_DENY in .env)."""
from pathlib import Path

from . import config

DEFAULT_DENY = "personal,.ssh,.gnupg,.env,password"


def deny_words():
    raw = config.get("FILE_DENY", DEFAULT_DENY)
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def denied(path):
    """True when any part of the path contains a deny word."""
    words = deny_words()
    return any(w in part.lower() for part in Path(path).parts for w in words)


def inside_home(path):
    try:
        Path(path).expanduser().resolve().relative_to(Path.home().resolve())
        return True
    except (ValueError, OSError):
        return False


def readable(path):
    """True for a path inside the home folder that is not on the deny list. Links are followed before the checks."""
    try:
        real = Path(path).expanduser().resolve()
    except OSError:
        return False
    return inside_home(real) and not denied(real) and not denied(path)
