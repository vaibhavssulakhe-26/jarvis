"""Paths and settings. Secrets come from the .env file, never from the code."""
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
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
    return os.environ.get(name, default).strip()


ASSISTANT = get("ASSISTANT_NAME", "Ana")
PET_NAME = get("USER_PET_NAME") or get("USER_NAME")
SHORT_NAME = get("USER_SHORT_NAME") or get("USER_NAME")
FULL_NAME = get("USER_FULL_NAME") or SHORT_NAME
VOICE = Path.home() / "piper-voices" / (get("ANA_VOICE", "en_US-amy-medium") + ".onnx")
RUNTIME = Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp") / "ana"


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
    """Wake word models in models/. A custom one (not Jarvis) is used when it exists."""
    shared = {"embedding_model", "melspectrogram"}
    files = sorted(p for p in MODELS.glob("*.onnx") if p.stem not in shared)
    custom = [p for p in files if "jarvis" not in p.name.lower()]
    return custom or files


def wake_names():
    return [re.sub(r"_v[0-9].*$", "", p.stem).replace("_", " ") for p in wake_files()]


def wake_label():
    return " / ".join(n.upper() for n in wake_names()) or "NONE"
