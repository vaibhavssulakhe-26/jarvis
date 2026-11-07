"""Paths and settings. Secrets come from the .env file, never from the code."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = Path(os.environ.get("JARVIS_DATA") or ROOT / "data")
MODELS = ROOT / "models"
ENV_FILE = ROOT / ".env"


def load_env():
    try:
        lines = ENV_FILE.read_text().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()


def get(name, default=""):
    """Read a setting. JARVIS_* names fall back to the older ANA_* name."""
    value = os.environ.get(name)
    if value is None and name.startswith("JARVIS_"):
        value = os.environ.get("ANA_" + name[len("JARVIS_"):])
    return (default if value is None else value).strip()


def stt_cloud():
    """True when speech recognition should use Groq. STT or JARVIS_STT, and g / groq / cloud all count."""
    value = (get("STT") or get("JARVIS_STT", "local")).lower()
    return value in ("groq", "g", "cloud")


def flag(name, default=False):
    raw = get(name, "true" if default else "false").lower()
    return raw in ("1", "true", "yes", "on")


ASSISTANT = get("ASSISTANT_NAME", "Jarvis")
PET_NAME = get("USER_PET_NAME") or get("USER_NAME")
SHORT_NAME = get("USER_SHORT_NAME") or get("USER_NAME")
FULL_NAME = get("USER_FULL_NAME") or SHORT_NAME
GOD_NAME = get("USER_GOD_NAME")
OTHER_NAMES = [n.strip() for n in get("USER_OTHER_NAMES").split(",") if n.strip()]
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "jarvis"
_old_projects = Path.home() / "ana-projects"
PROJECTS = Path.home() / ("ana-projects" if _old_projects.is_dir() and not (Path.home() / "jarvis-projects").is_dir()
                          else "jarvis-projects")


def runtime_file(name):
    """A path for scratch audio that other users cannot read."""
    RUNTIME.mkdir(mode=0o700, exist_ok=True)
    return RUNTIME / name


def discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


def wake_files():
    """The model named by WAKE_WORD: a path to an .onnx file, or a name matching a file in models/."""
    wanted = get("WAKE_WORD", "alexa")
    path = Path(wanted).expanduser()
    if path.suffix == ".onnx" and path.is_file():
        return [path]
    shared = {"embedding_model", "melspectrogram", "silero_vad"}
    files = sorted(p for p in MODELS.glob("*.onnx") if p.stem not in shared)
    named = [p for p in files if p.stem.lower().startswith(wanted.lower())]
    return named or files


def wake_names():
    return [re.sub(r"_v[0-9].*$", "", p.stem).replace("_", " ") for p in wake_files()]


def wake_label():
    return " / ".join(n.upper() for n in wake_names()) or "NONE"
