"""The macOS backend. Written from the documentation of the tools it calls and not yet run on a Mac (see the README). A function that is
missing here makes the interface raise Unsupported, which is spoken as "... is not supported on this system"."""
import os
import plistlib
import shutil
import subprocess
import time
from pathlib import Path

from ..core.errors import ToolError

NAME = "mac"
_QUIET = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
SUPPORT = Path.home() / "Library" / "Application Support" / "Jarvis"


def _have(tool):
    return shutil.which(tool) is not None


def _osa(*lines, timeout=5):
    """Run AppleScript lines and return what it printed ('' on failure)."""
    cmd = ["osascript"]
    for line in lines:
        cmd += ["-e", line]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def _q(text):
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


# ---------- folders ----------
def lock_dir():
    return Path(os.environ.get("TMPDIR") or "/tmp")


def runtime_dir():
    return lock_dir() / "jarvis"


def state_dir():
    return SUPPORT / "state"


def data_dir(root):
    return SUPPORT / "data"


# ---------- clipboard ----------
def clipboard_read():
    return subprocess.run(["pbpaste"], capture_output=True, timeout=5).stdout.decode(errors="replace").strip()


def clipboard_write(text):
    subprocess.run(["pbcopy"], input=str(text).encode(), timeout=5, **_QUIET)
    return True


def clipboard_write_image(path):
    _osa(f'set the clipboard to (read (POSIX file "{_q(path)}") as «class PNGf»)')


def clipboard_watch_ok():
    return True


# ---------- opening and capturing ----------
def open_ok():
    return True


def open_target(target):
    subprocess.Popen(["open", str(target)], start_new_session=True, **_QUIET)


def capture_screen(path):
    subprocess.run(["screencapture", "-x", str(path)], timeout=15, **_QUIET)
    if not Path(path).exists():
        raise ToolError("I could not save the screenshot. Allow screen recording for the terminal in System Settings, Privacy and Security.")


# ---------- windows (AppleScript through System Events; needs the Accessibility permission) ----------
def windows_ok():
    return True


def active_window(max_age=2.0):
    out = _osa('tell application "System Events"',
               'set p to first application process whose frontmost is true',
               'set t to ""',
               'try', 'set t to name of front window of p', 'end try',
               'return (name of p) & "\t" & t', 'end tell')
    if not out:
        return None
    app, _, title = out.partition("\t")
    return app, title


def window_find(patterns):
    names = _osa('tell application "System Events" to get name of every application process whose background only is false')
    running = [n.strip() for n in names.split(",") if n.strip()]
    return [n for n in running if any(p.lower() in n.lower() for p in patterns)]


def window_close(ids):
    for name in ids:
        _osa(f'tell application "{_q(name)}" to close every window')


def window_activate(wid):
    _osa(f'tell application "{_q(wid)}" to activate')


def close_active():
    _osa('tell application "System Events" to keystroke "w" using command down')


def minimise_active():
    _osa('tell application "System Events" to keystroke "m" using command down')


# ---------- notifications and power ----------
def notify(title, text, urgent=False):
    _osa(f'display notification "{_q(text)}" with title "{_q(title)}"')
    return True


def lock_screen():
    subprocess.Popen(["pmset", "displaysleepnow"], **_QUIET)


def power(action):
    if action == "suspend":
        subprocess.Popen(["pmset", "sleepnow"], **_QUIET)
    else:
        _osa('tell application "System Events" to ' + ("shut down" if action == "poweroff" else "restart"))


# ---------- sound and media ----------
def volume_get():
    out = _osa("output volume of (get volume settings)")
    return int(out) if out.isdigit() else None


def volume_set(percent):
    _osa(f"set volume output volume {max(0, min(100, int(percent)))}")


def volume_change(delta):
    now = volume_get()
    volume_set((now or 0) + delta)


def unmute():
    _osa("set volume output muted false")


_MUSIC = {"play-pause": "playpause", "play": "play", "pause": "pause", "next": "next track", "previous": "previous track"}


def media_control(cmd, players=None):
    """Controls the Music app only."""
    if _osa('application "Music" is running') != "true":
        raise ToolError("Media keys only work with the Music app on this system, and it is not open.")
    _osa(f'tell application "Music" to {_MUSIC[cmd]}')


def media_status():
    if _osa('application "Music" is running') != "true":
        return ""
    return {"playing": "Playing", "paused": "Paused"}.get(_osa('tell application "Music" to get player state as string'), "")


def audio_players():
    return ("afplay",)


def alarm_sound():
    return ["afplay", "/System/Library/Sounds/Glass.aiff"] if _have("afplay") else None


# ---------- keyboard (pynput; needs the Accessibility and Input Monitoring permissions) ----------
def _pynput():
    try:
        import pynput.keyboard as kb
    except ImportError:
        raise ToolError("Keyboard features on a Mac need pynput. Run: pip install pynput")
    return kb


def listen_key(key_name, on_press, on_release):
    kb = _pynput()
    wanted = key_name.removeprefix("KEY_").lower()
    key = getattr(kb.Key, wanted, None) or kb.KeyCode.from_char(wanted)
    with kb.Listener(on_press=lambda k: on_press() if k == key else None,
                     on_release=lambda k: on_release() if k == key else None) as listener:
        listener.join()


def _tap(*keys):
    kb = _pynput()
    ctl = kb.Controller()
    time.sleep(0.3)
    for k in keys:
        ctl.press(k)
    for k in reversed(keys):
        ctl.release(k)


def send_paste(terminal=False):
    kb = _pynput()
    _tap(kb.Key.cmd, "v")


def send_enter():
    kb = _pynput()
    _tap(kb.Key.enter)


# ---------- background services (launchd) ----------
def _agents():
    return Path.home() / "Library" / "LaunchAgents"


def service_active(name):
    r = subprocess.run(["launchctl", "list"], capture_output=True, text=True, timeout=3)
    return f"com.jarvis.{name}" in r.stdout


def _write_agent(label, command, extra, workdir=None):
    _agents().mkdir(parents=True, exist_ok=True)
    plist = {"Label": label, "ProgramArguments": [str(c) for c in command], **extra}
    if workdir:
        plist["WorkingDirectory"] = str(workdir)
    path = _agents() / f"{label}.plist"
    path.write_bytes(plistlib.dumps(plist))
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True, timeout=10)
    r = subprocess.run(["launchctl", "load", str(path)], capture_output=True, timeout=10)
    return path, r.returncode == 0


def install_schedule(name, command, every_minutes, description, workdir):
    path, ok = _write_agent(f"com.jarvis.{name}", command, {"StartInterval": int(every_minutes) * 60, "RunAtLoad": True}, workdir)
    return f"launchd job {path.name} loaded" if ok else f"wrote {path}; loading it failed, run: launchctl load {path}"


def install_autostart(name, command):
    path, ok = _write_agent(f"com.jarvis.{name}", command, {"RunAtLoad": True})
    return f"login item {path.name} loaded" if ok else f"wrote {path}; loading it failed, run: launchctl load {path}"
