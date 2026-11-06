"""The focused window (app, title), read locally. Used by notes and the distraction guard."""
import os
import re
import shutil
import subprocess
import tempfile
import time

_cache = {"t": 0.0, "value": None}
_method = [None]
_warned = [False]
KWIN_SCRIPT = ('var w = workspace.activeWindow;\n'
               'print("JARVIS_ACTIVE\\t" + (w ? w.resourceClass : "") + "\\t" + (w ? w.caption : ""));\n')


def _run(cmd, timeout=3):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return r.stdout.strip() if r.returncode == 0 else ""


def _kdotool():
    if not shutil.which("kdotool"):
        return None
    title = _run(["kdotool", "getactivewindow", "getwindowname"])
    app = _run(["kdotool", "getactivewindow", "getwindowclassname"])
    return (app, title) if (app or title) else None


def _kwin_script():
    """Ask KWin to run a one-line script and read what it printed from the user journal."""
    if not shutil.which("gdbus") or not shutil.which("journalctl"):
        return None
    fd, path = tempfile.mkstemp(suffix=".js")
    with os.fdopen(fd, "w") as f:
        f.write(KWIN_SCRIPT)
    name = "jarvis-active"
    try:
        out = _run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
                    "--method", "org.kde.kwin.Scripting.loadScript", path, name])
        m = re.search(r"(\d+)", out)
        if not m:
            return None
        _run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path",
              f"/Scripting/Script{m.group(1)}", "--method", "org.kde.kwin.Script.run"])
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
        _run(["gdbus", "call", "--session", "--dest", "org.kde.KWin", "--object-path", "/Scripting",
              "--method", "org.kde.kwin.Scripting.unloadScript", name])
        try:
            os.remove(path)
        except OSError:
            pass


def available():
    return _method[0] != "none"


def active_window(max_age=2.0):
    """(app, title) of the focused window, or None when it cannot be read."""
    if _method[0] == "none":
        return None
    if time.time() - _cache["t"] < max_age:
        return _cache["value"]
    value = None
    for name, fn in (("kdotool", _kdotool), ("kwin", _kwin_script)):
        if _method[0] not in (None, name):
            continue
        try:
            value = fn()
        except (subprocess.SubprocessError, OSError):
            value = None
        if value:
            _method[0] = name
            break
        if _method[0] == name:
            break
    if value is None and _method[0] is None:
        _method[0] = "none"
        if not _warned[0]:
            _warned[0] = True
            print("  (no way to read the active window: install kdotool; window features are off)")
    _cache["t"], _cache["value"] = time.time(), value
    return value


def _kd(*args):
    if not shutil.which("kdotool"):
        return ""
    try:
        return _run(["kdotool", *args])
    except (subprocess.SubprocessError, OSError):
        return ""


def find_ids(patterns):
    """Window ids whose class matches any pattern. Titles are not searched, so a page that mentions an app does not match."""
    ids = []
    for pat in patterns:
        for wid in _kd("search", "--class", "--classname", pat).split():
            if wid not in ids:
                ids.append(wid)
    return ids


def close(ids):
    for wid in ids:
        _kd("windowclose", wid)


def activate(wid):
    _kd("windowactivate", wid)


def close_active():
    _kd("getactivewindow", "windowclose")


def minimise_active():
    _kd("getactivewindow", "windowminimize")
