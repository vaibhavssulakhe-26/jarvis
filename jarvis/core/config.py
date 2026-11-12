"""Paths and settings. Secrets come from the .env file, never from the code."""
import os
import re
from pathlib import Path

from .. import platform

ROOT = Path(__file__).resolve().parent.parent.parent
MODELS = ROOT / "models"
ENV_FILE = ROOT / ".env"


def _read_env(path):
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _profile_name():
    """JARVIS_PROFILE from the environment, or from the base .env. Letters, digits, dash and underscore only."""
    name = os.environ.get("JARVIS_PROFILE", "")
    if not name:
        try:
            m = re.search(r"^JARVIS_PROFILE\s*=\s*(\S+)", ENV_FILE.read_text(), re.M)
            name = m.group(1).strip("\"'") if m else ""
        except OSError:
            name = ""
    return name if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", name) else ""


PROFILE = _profile_name()


def load_env():
    """A profile's own file (.env.<profile>) is read first, so its USER_NAME and the like win over the shared .env."""
    if PROFILE:
        _read_env(ROOT / f".env.{PROFILE}")
    _read_env(ENV_FILE)


load_env()
_base_data = platform.data_dir(ROOT)
DATA = Path(os.environ.get("JARVIS_DATA") or (_base_data / "profiles" / PROFILE if PROFILE else _base_data))


def get(name, default=""):
    """Read a setting. JARVIS_* names fall back to the older ANA_* name."""
    value = os.environ.get(name)
    if value is None and name.startswith("JARVIS_"):
        value = os.environ.get("ANA_" + name[len("JARVIS_"):])
    return (default if value is None else value).strip()


def stt_cloud():
    """True when speech recognition should use Groq. STT or JARVIS_STT, and g / groq / cloud all count."""
    value = (get("STT") or get("JARVIS_STT", "local")).lower()
    return value in ("groq", "g", "cloud") and not offline()


def brain_mode():
    """'hybrid' (cloud first, offline backup) or 'offline' (cloud providers are never called)."""
    return "offline" if get("BRAIN", "hybrid").lower() in ("offline", "local") else "hybrid"


def offline():
    return brain_mode() == "offline"


def flag(name, default=False):
    raw = get(name, "true" if default else "false").lower()
    return raw in ("1", "true", "yes", "on")


ASSISTANT = get("ASSISTANT_NAME", "Jarvis")
NICKNAME = get("USER_NICKNAME") or get("USER_NAME")
PET_NAME = get("USER_NICKNAME") or get("USER_PET_NAME") or get("USER_NAME")
SHORT_NAME = get("USER_SHORT_NAME") or get("USER_NAME")
FULL_NAME = get("USER_FULL_NAME") or SHORT_NAME
GOD_NAME = get("USER_GOD_NAME")
RUNTIME = platform.runtime_dir() / PROFILE if PROFILE else platform.runtime_dir()
_old_projects = Path.home() / "ana-projects"
PROJECTS = Path.home() / ("ana-projects" if _old_projects.is_dir() and not (Path.home() / "jarvis-projects").is_dir()
                          else "jarvis-projects")


def runtime_file(name):
    """A path for scratch audio that other users cannot read."""
    RUNTIME.mkdir(mode=0o700, parents=True, exist_ok=True)
    return RUNTIME / name


def discard(path):
    try:
        os.remove(path)
    except OSError:
        pass


BUNDLED_WAKE = ("alexa", "hey_jarvis", "hey_mycroft", "hey_rhasspy", "timer", "weather")


def wake_files():
    """The models named by WAKE_WORD (comma separated; an .onnx path or a name matching a file in models/), plus any custom
    wake model dropped into models/ that is not one of the bundled ones."""
    shared = {"embedding_model", "melspectrogram", "silero_vad"}
    files = sorted(p for p in MODELS.glob("*.onnx") if p.stem not in shared)
    chosen = []
    for wanted in [w.strip() for w in get("WAKE_WORD", "alexa").split(",") if w.strip()]:
        path = Path(wanted).expanduser()
        if path.suffix == ".onnx" and path.is_file():
            chosen.append(path)
        else:
            chosen += [p for p in files if p.stem.lower().startswith(wanted.lower())]
    if not chosen:
        return files
    chosen += [p for p in files if not p.stem.lower().startswith(BUNDLED_WAKE)]
    return list(dict.fromkeys(chosen))


def wake_names():
    return [re.sub(r"_v[0-9].*$", "", p.stem).replace("_", " ") for p in wake_files()]


def wake_label():
    return " / ".join(n.upper() for n in wake_names()) or "NONE"
