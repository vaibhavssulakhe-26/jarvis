"""The holo viewer from handctl, driven through its own bridge.py (a Unix socket in $XDG_RUNTIME_DIR/handctl, local only). Jarvis never talks on that socket
itself: it runs `<HANDCTL_DIR>/.venv/bin/python bridge.py load NAME|reset|close`. To start the viewer it runs handctl's hand_mouse.py --holo itself (bridge.py open
throws the viewer's error output away), keeps stderr in a private log and reports the first useful line of it if the viewer does not come up; without
hand_mouse.py it falls back to `bridge.py open`. The viewer only loads files from handctl's models folder by name, so a model
made by Jarvis is linked there as jarvis-<name>.stl (a symlink to models/<name>/model.stl, nothing is copied). The viewer reads that folder once at start, so a new
name makes Jarvis restart it."""
import atexit
import os
import re
import socket
import subprocess
import time
from pathlib import Path

from .core import config
from .core.errors import ToolError

START_WAIT = 20.0
VIEWER_SCRIPT = "hand_mouse.py"
STOP_WAIT = 5.0
CALL_SECONDS = 15
PREFIX = "jarvis-"
GENERIC = {"", "it", "that", "this", "the model", "the hologram", "the holo", "the object", "the part", "model", "my model"}
_s = {"started": False}


def home():
    return Path(config.get("HANDCTL_DIR") or "~/Documents/handctl").expanduser()


def python():
    return home() / ".venv" / "bin" / "python"


def problem():
    """Why holo cannot be used, or an empty string when it is set up."""
    if not (home() / "bridge.py").is_file():
        return f"handctl is not at {home()}. Set HANDCTL_DIR in the .env file."
    if not python().is_file():
        return f"handctl has no virtual environment at {python().parent.parent}."
    return ""


def ready():
    return not problem()


def _socket_path():
    base = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(base) if base and os.path.isdir(base) else Path.home() / ".cache"
    return root / "handctl" / "holo.sock"


def _alive():
    """True when a viewer is listening. Only connects; no token is read."""
    path = _socket_path()
    if not path.exists():
        return False
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.connect(str(path))
        return True
    except OSError:
        return False
    finally:
        s.close()


def running():
    return _alive()


def _run(args):
    return subprocess.run([str(python()), str(home() / "bridge.py"), *args], cwd=home(), capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=CALL_SECONDS, stdin=subprocess.DEVNULL)


def call(*args):
    """Run one bridge command. Raises a ToolError with one speakable sentence when it fails."""
    why = problem()
    if why:
        raise ToolError(why)
    try:
        r = _run(list(args))
    except subprocess.TimeoutExpired:
        raise ToolError("The hologram viewer did not answer in time.")
    except OSError as e:
        raise ToolError(f"I could not run the handctl bridge: {e.strerror or e}.")
    if r.returncode != 0:
        said = " ".join((r.stdout or r.stderr or "").split())[:120]
        raise ToolError(f"The hologram viewer refused: {said or 'no reason given'}.")


def _wait(want, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _alive() == want:
            return True
        time.sleep(0.25)
    return _alive() == want


def first_error(text):
    """The first useful line of a viewer's stderr: the exception that ends a traceback ("ModuleNotFoundError: No module named 'evdev'"), else the
    first line that mentions an error, else the last line. Empty when there is nothing."""
    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
    for l in reversed(lines):
        if re.match(r"^(?:[\w.]+\.)?\w*(?:Error|Exception|Exit)\b", l):
            return l[:160]
    for l in lines:
        if re.search(r"error|cannot|can't|could not|failed|no module|not found", l, re.I):
            return l[:160]
    return lines[-1][:160] if lines else ""


def _log_path():
    return config.runtime_file("holo-viewer.log")


def _spawn():
    """Start the viewer directly, its error output going to a private log, so a failure can be read back. (bridge.py open discards it.)"""
    with open(_log_path(), "w", encoding="utf-8") as log:
        return subprocess.Popen([str(python()), str(home() / VIEWER_SCRIPT), "--holo"], cwd=home(), stdin=subprocess.DEVNULL,
                                stdout=subprocess.DEVNULL, stderr=log, start_new_session=True)


def _log_text():
    try:
        return _log_path().read_text(encoding="utf-8", errors="replace")[-4000:]
    except OSError:
        return ""


def _wait_up(proc, seconds):
    """True when the viewer's socket answers. Gives up early when the child process has already ended."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if _alive():
            return True
        if proc is not None and proc.poll() is not None:
            return _alive()
        time.sleep(0.25)
    return _alive()


def start():
    """Make sure a viewer is running. Returns True when this call started it. On failure the error says why, from the viewer's own stderr."""
    if _alive():
        return False
    proc = None
    if (home() / VIEWER_SCRIPT).is_file():
        try:
            proc = _spawn()
        except OSError as e:
            raise ToolError(f"I could not start the hologram viewer: {e.strerror or e}.")
    else:
        call("open")
    if not _wait_up(proc, START_WAIT):
        line = first_error(_log_text()) if proc is not None else ""
        if proc is not None and proc.poll() is None:
            proc.terminate()
        if line:
            raise ToolError(f"The hologram viewer did not start: {line}.")
        if proc is not None and proc.poll() is not None:
            raise ToolError(f"The hologram viewer stopped right away (exit code {proc.returncode}) and said nothing.")
        raise ToolError(f"The hologram viewer did not start within {START_WAIT:.0f} seconds. Check that the camera is free and that handctl runs on its own.")
    _s["started"] = True
    return True


def stop():
    """Close the viewer if Jarvis started it; used at exit."""
    if _s["started"] and _alive() and not problem():
        try:
            _run(["close"])
        except (OSError, subprocess.SubprocessError):
            pass
    _s["started"] = False


atexit.register(stop)


# ---------- models ----------
def _folder():
    return home() / "models"


def _link(slug, src):
    """Make models/jarvis-<slug>.stl in handctl point at the model. Returns True when the name is new to the viewer."""
    folder = _folder()
    link = folder / f"{PREFIX}{slug}.stl"
    if link.is_symlink() and Path(os.readlink(link)) == Path(src):
        return False
    try:
        folder.mkdir(exist_ok=True)
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(src)
    except OSError as e:
        raise ToolError(f"I could not put the model where handctl looks for it: {e.strerror or e}.")
    return True


def resolve(name=""):
    """(load name, spoken name, source file or None) for a spoken model name. Jarvis models first, then handctl's own files."""
    from .actions import modeler
    raw = " ".join(str(name).lower().split())
    raw = re.sub(r"^(?:the|my)\s+", "", raw) if raw not in GENERIC else raw
    try:
        folder = modeler.current("" if raw in GENERIC else raw)
        src = folder / "model.stl"
        if src.is_file():
            return PREFIX + folder.name, folder.name.replace("-", " "), src.resolve()
    except ToolError:
        if raw in GENERIC:
            raise
    stems = [p.stem for p in _folder().glob("*") if p.suffix.lower() in (".stl", ".obj") and not p.stem.startswith(PREFIX)] if _folder().is_dir() else []
    flat = modeler.squash(raw)
    hit = [s for s in stems if s.lower() == raw] or [s for s in stems if s.lower().startswith(raw)] or [s for s in stems if flat and modeler.squash(s) == flat]
    if raw and len(hit) == 1:
        return hit[0], hit[0], None
    raise ToolError(f"I do not have a model called {raw[:30]}.")


def known(name):
    try:
        resolve(name)
        return True
    except ToolError:
        return False


def wants(name, explicit):
    """Is "show <name>" about a model? Yes when the hologram was named. Otherwise a generic word such as "it" counts only if a model was made in the last hour,
    and any other name must be a model that exists."""
    from .actions import modeler
    if explicit:
        return True
    if " ".join(str(name).lower().split()) in GENERIC:
        return ready() and modeler.recent()
    return known(name)


def show(name=""):
    """Show a model in the viewer, starting or restarting it when needed. Returns the spoken name."""
    why = problem()
    if why:
        raise ToolError(why)
    load, spoken, src = resolve(name)
    new = _link(load[len(PREFIX):], src) if src else False
    if new and _alive():
        call("close")
        _wait(False, STOP_WAIT)
        _s["started"] = False
    start()
    call("load", load)
    if src:
        from .core import refs
        refs.remember("model", load[len(PREFIX):], src)
    return spoken


def reset():
    if not _alive():
        raise ToolError("The hologram is not open.")
    call("reset")


def close():
    if not _alive():
        _s["started"] = False
        raise ToolError("The hologram is not open.")
    call("close")
    if not _wait(False, STOP_WAIT):
        raise ToolError("I told the hologram viewer to close, but it is still running.")
    _s["started"] = False
