"""Paths and settings. Secrets come from the .env file, never from the code."""
import os
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
PET_NAME = get("USER_PET_NAME") or get("USER_NAME") or "there"
SHORT_NAME = get("USER_SHORT_NAME") or get("USER_NAME")
FULL_NAME = get("USER_FULL_NAME") or SHORT_NAME
VOICE = Path.home() / "piper-voices" / (get("ANA_VOICE", "en_US-amy-medium") + ".onnx")
