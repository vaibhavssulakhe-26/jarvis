"""The Linux backend (written for Fedora KDE on Wayland; X11 tools are fallbacks). Every command-line tool that only exists on Linux is
called from this file and nowhere else."""
import os
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from ..core.errors import ToolError

NAME = "linux"
_QUIET = dict(stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _have(tool):
    return shutil.which(tool) is not None


def _run(cmd, timeout=3):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def _launch(cmd):
    if not _have(cmd[0]):
        raise ToolError(f"{cmd[0]} is not installed.")
    subprocess.Popen(cmd, start_new_session=True, **_QUIET)


# ---------- folders ----------
def lock_dir():
    return Path(os.environ.get("XDG_RUNTIME_DIR") or "/tmp")


def runtime_dir():
    return lock_dir() / "jarvis"


def state_dir():
    return Path(os.environ.get("XDG_STATE_HOME") or (Path.home() / ".local" / "state")) / "jarvis"


def data_dir(root):
    return Path(root) / "data"


# ---------- clipboard ----------
def clipboard_read():
    for cmd in (["wl-paste", "--no-newline", "--type", "text"],
                ["xclip", "-selection", "clipboard", "-o"],
                ["xsel", "--clipboard", "--output"]):
        if _have(cmd[0]):
            r = subprocess.run(cmd, capture_output=True, timeout=5)
            return r.stdout.decode(errors="replace").strip() if r.returncode == 0 else ""
    raise ToolError("I need wl-paste to read the clipboard.")


def clipboard_write(text):
    """Put text on the clipboard. False when no clipboard tool is installed."""
    for cmd in (["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]):
        if _have(cmd[0]):
            subprocess.run(cmd, input=str(text).encode(), timeout=5, **_QUIET)
            return True
    return False


def clipboard_write_image(path):
    if not _have("wl-copy"):
        raise ToolError("I need wl-copy to send a picture.")
    with open(path, "rb") as f:
        subprocess.run(["wl-copy", "--type", "image/png"], stdin=f, timeout=10, check=True, **_QUIET)


def clipboard_watch_ok():
    return _have("wl-paste")


# ---------- opening and capturing ----------
def open_ok():
    return _have("xdg-open")


def open_target(target):
    """Open a web address or a file with its default app."""
    if not open_ok():
        raise ToolError("I need xdg-open for that.")
    subprocess.Popen(["xdg-open", str(target)], start_new_session=True, **_QUIET)


def capture_screen(path):
    path = Path(path)
    # scrot and gnome-screenshot only work on X11 or GNOME, so they are fallbacks behind spectacle
    for cmd in (["spectacle", "-b", "-n", "-f", "-o", str(path)], ["grim", str(path)],
                ["gnome-screenshot", "-f", str(path)], ["scrot", "-o", str(path)]):
        if _have(cmd[0]):
            break
    else:
        raise ToolError("I need spectacle to take a screenshot.")
    subprocess.run(cmd, timeout=15, **_QUIET)
    if not path.exists():
        time.sleep(1.5)
    if not path.exists():
        raise ToolError("I could not save the screenshot.")


# ---------- windows (kdotool, or a KWin script) ----------
KWIN_SCRIPT = ('var w = workspace.activeWindow;\n'
               'print("JARVIS_ACTIVE\\t" + (w ? w.resourceClass : "") + "\\t" + (w ? w.caption : ""));\n')
_win = {"t": 0.0, "value": None, "method": None, "warned": False}


def _kdotool_active():
    if not _have("kdotool"):
        return None
    title = _run(["kdotool", "getactivewindow", "getwindowname"])
    app = _run(["kdotool", "getactivewindow", "getwindowclassname"])
    return (app, title) if (app or title) else None


def _kwin_active():
    """Ask KWin to run a one-line script and read what it printed from the user journal."""
    if not _have("gdbus") or not _have("journalctl"):
        return None
    fd, path = tempfile.mkstemp(suffix=".js")
    with os.fdopen(fd, "w") as f:
        f.write(KWIN_SCRIPT)
    name = "jarvis-active"
    kwin = ["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path"]
    try:
        out = _run(kwin + ["/Scripting", "--method", "org.kde.kwin.Scripting.loadScript", path, name])
        m = re.search(r"(\d+)", out)
        if not m:
            return None
        _run(kwin + [f"/Scripting/Script{m.group(1)}", "--method", "org.kde.kwin.Script.run"])
        time.sleep(0.25)
        log = _run(["journalctl", "--user", "-n", "40", "--since", "-5s", "-o", "cat", "--no-pager"])
        hits = [ln for ln in log.splitlines() if "JARVIS_ACTIVE" in ln]
        if not hits:
            return None
        _, app, title = (hits[-1].split("JARVIS_ACTIVE", 1)[1].split("\t") + ["", ""])[:3]
        return (app, title) if (app or title) else None
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        _run(kwin + ["/Scripting", "--method", "org.kde.kwin.Scripting.unloadScript", name])
        try:
            os.remove(path)
        except OSError:
            pass


def windows_ok():
    return _win["method"] != "none"


def active_window(max_age=2.0):
    """(app, title) of the focused window, or None when it cannot be read."""
    if _win["method"] == "none":
        return None
    if time.time() - _win["t"] < max_age:
        return _win["value"]
    value = None
    for name, fn in (("kdotool", _kdotool_active), ("kwin", _kwin_active)):
        if _win["method"] not in (None, name):
            continue
        try:
            value = fn()
        except (subprocess.SubprocessError, OSError):
            value = None
        if value:
            _win["method"] = name
            break
        if _win["method"] == name:
            break
    if value is None and _win["method"] is None:
        _win["method"] = "none"
        if not _win["warned"]:
            _win["warned"] = True
            print("  (no way to read the active window: install kdotool; window features are off)")
    _win["t"], _win["value"] = time.time(), value
    return value


def _kd(*args):
    if not _have("kdotool"):
        return ""
    try:
        return _run(["kdotool", *args])
    except (subprocess.SubprocessError, OSError):
        return ""


def window_find(patterns):
    """Window ids whose class matches any pattern. Titles are not searched, so a page that mentions an app does not match."""
    ids = []
    for pat in patterns:
        for wid in _kd("search", "--class", "--classname", pat).split():
            if wid not in ids:
                ids.append(wid)
    return ids


def window_close(ids):
    for wid in ids:
        _kd("windowclose", wid)


def window_activate(wid):
    _kd("windowactivate", wid)


def close_active():
    _kd("getactivewindow", "windowclose")


def minimise_active():
    if not _have("kdotool"):
        raise ToolError("I need kdotool to minimise windows.")
    _kd("getactivewindow", "windowminimize")


# ---------- notifications and power ----------
def notify(title, text, urgent=False):
    if not _have("notify-send"):
        return False
    subprocess.run(["notify-send", *(["-u", "critical"] if urgent else []), title, text], timeout=5)
    return True


_inhibit = {"cookie": None}


def _dbus_call(method, *args):
    from PyQt6.QtDBus import QDBus, QDBusConnection, QDBusMessage
    msg = QDBusMessage.createMethodCall("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                                        "org.freedesktop.Notifications", method)
    msg.setArguments(list(args))
    return QDBusConnection.sessionBus().call(msg, QDBus.CallMode.Block, 2000)


def inhibit_notifications(on):
    """Plasma's do not disturb. It ends by itself if Jarvis exits. Returns True if it changed."""
    if on and _inhibit["cookie"] is None:
        reply = _dbus_call("Inhibit", "Jarvis", "Focus session", {})
        if reply.arguments():
            _inhibit["cookie"] = int(reply.arguments()[0])
            return True
    elif not on and _inhibit["cookie"] is not None:
        from PyQt6.QtCore import QMetaType
        from PyQt6.QtDBus import QDBusArgument
        _dbus_call("UnInhibit", QDBusArgument(_inhibit["cookie"], QMetaType.Type.UInt.value))
        _inhibit["cookie"] = None
        return True
    return False


def lock_screen():
    _launch(["loginctl", "lock-session"])


def power(action):
    """action: suspend, poweroff or reboot."""
    _launch(["systemctl", action])


# ---------- sound and display ----------
SINK = "@DEFAULT_AUDIO_SINK@"


def _wp(*a):
    subprocess.run(["wpctl", *a], timeout=5)


def volume_get():
    r = subprocess.run(["wpctl", "get-volume", SINK], capture_output=True, text=True, timeout=5)
    m = re.search(r"([0-9.]+)", r.stdout)
    return round(float(m.group(1)) * 100) if m else None


def volume_set(percent):
    _wp("set-volume", "-l", "1.0", SINK, f"{percent / 100:.2f}")


def volume_change(delta):
    if delta >= 0:
        _wp("set-volume", "-l", "1.0", SINK, f"{delta}%+")
    else:
        _wp("set-volume", SINK, f"{-delta}%-")


def unmute():
    _wp("set-mute", SINK, "0")


def _brightness(arg):
    if not _have("brightnessctl"):
        raise ToolError("I need brightnessctl for that. Install it with dnf and try again.")
    if subprocess.run(["brightnessctl", "set", arg], capture_output=True, timeout=5).returncode:
        raise ToolError("I could not change the brightness.")


def brightness_change(delta):
    _brightness(f"{abs(delta)}%" + ("+" if delta >= 0 else "-"))


def brightness_set(percent):
    _brightness(f"{min(int(percent), 100)}%")


def media_control(cmd, players=None):
    """cmd: play-pause, play, pause, next or previous, sent to whatever player is running (playerctl)."""
    if not _have("playerctl"):
        raise ToolError("Media control needs playerctl. Install it with: sudo dnf install playerctl")
    subprocess.run(["playerctl", *(["-p", players] if players else []), cmd], capture_output=bool(players), timeout=5)


def media_status():
    """'Playing', 'Paused' or '' when nothing reports in."""
    if not _have("playerctl"):
        return ""
    try:
        return subprocess.run(["playerctl", "status"], capture_output=True, text=True, timeout=1.5).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def audio_players():
    return ("pw-play", "paplay", "aplay")


def alarm_sound():
    """A command that plays a short alarm, or None."""
    for cmd in (["canberra-gtk-play", "-i", "alarm-clock-elapsed"],
                ["paplay", "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"]):
        if _have(cmd[0]):
            return cmd
    return None


# ---------- keyboard (evdev needs the input group) ----------
def listen_key(key_name, on_press, on_release):
    """Block and call on_press / on_release for the named key (such as KEY_F9) on every keyboard. Raises PermissionError without the input group."""
    import selectors

    import evdev
    from evdev import ecodes
    code = getattr(ecodes, key_name, None)
    if code is None:
        raise ToolError(f"{key_name} is not a known key name.")
    sel = selectors.DefaultSelector()
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        keys = dev.capabilities().get(ecodes.EV_KEY, [])
        if ecodes.KEY_A in keys and ecodes.KEY_ENTER in keys and "jarvis" not in dev.name.lower():
            sel.register(dev, selectors.EVENT_READ)
    if not sel.get_map():
        raise RuntimeError("no keyboard found")
    while True:
        for key, _ in sel.select():
            for ev in key.fileobj.read():
                if ev.type == ecodes.EV_KEY and ev.code == code:
                    if ev.value == 1:
                        on_press()
                    elif ev.value == 0:
                        on_release()


def _type(*steps):
    """Each step is (key names pressed together, pause in seconds after)."""
    from evdev import UInput, ecodes as e
    ui = UInput({e.EV_KEY: [e.KEY_ENTER, e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_V]}, name="jarvis-keyboard")
    try:
        time.sleep(0.5)
        for keys, pause in steps:
            codes = [getattr(e, "KEY_" + k) for k in keys]
            for code in codes:
                ui.write(e.EV_KEY, code, 1)
            ui.syn()
            time.sleep(0.05)
            for code in reversed(codes):
                ui.write(e.EV_KEY, code, 0)
            ui.syn()
            time.sleep(pause)
    finally:
        ui.close()


def send_paste(terminal=False):
    """Press the paste shortcut in the focused window (Ctrl+Shift+V in a terminal)."""
    _type((("LEFTCTRL",) + (("LEFTSHIFT",) if terminal else ()) + ("V",), 0.1))


def send_enter():
    _type((("ENTER",), 0.2))


# ---------- background services ----------
def service_active(name):
    try:
        return subprocess.run(["systemctl", "--user", "is-active", "--quiet", name], timeout=3).returncode == 0
    except Exception:
        return False


def _unit_dir():
    return Path.home() / ".config" / "systemd" / "user"


def install_schedule(name, command, every_minutes, description, workdir):
    """A user-level systemd timer that runs `command` (a list) every few minutes, also after the laptop was off. Returns a status line."""
    unit = _unit_dir()
    unit.mkdir(parents=True, exist_ok=True)
    (unit / f"{name}.service").write_text(
        f"[Unit]\nDescription={description}\n\n[Service]\nType=oneshot\nWorkingDirectory={workdir}\n"
        f"ExecStart={' '.join(str(c) for c in command)}\nMemoryMax=600M\nTimeoutStartSec=300\n")
    (unit / f"{name}.timer").write_text(
        f"[Unit]\nDescription={description}, every {every_minutes} minutes\n\n[Timer]\nOnBootSec=2min\n"
        f"OnUnitActiveSec={every_minutes}min\nPersistent=true\n\n[Install]\nWantedBy=timers.target\n")
    if not _have("systemctl"):
        return f"wrote the unit files in {unit}; systemctl is missing, so enable them yourself"
    subprocess.run(["systemctl", "--user", "daemon-reload"], timeout=15)
    r = subprocess.run(["systemctl", "--user", "enable", "--now", f"{name}.timer"], capture_output=True, timeout=15)
    return f"timer {name}.timer enabled" if r.returncode == 0 else f"wrote the unit files in {unit}; enabling the timer failed"


def install_autostart(name, command):
    """Start Jarvis at login through an XDG autostart entry."""
    folder = Path.home() / ".config" / "autostart"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{name}.desktop").write_text(
        f"[Desktop Entry]\nType=Application\nName={name}\nExec={' '.join(str(c) for c in command)}\nX-GNOME-Autostart-enabled=true\n")
    return f"autostart entry written to {folder / (name + '.desktop')}"
