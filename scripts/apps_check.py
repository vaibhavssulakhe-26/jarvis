"""Checks app opening, closing and brightness with mocks. Nothing is launched or changed. Run: python scripts/apps_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
tmp = Path(tempfile.mkdtemp(prefix="jarvis-apps-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")

from jarvis.actions import tools  # noqa: E402
from jarvis.actions import apps, windows  # noqa: E402
from jarvis.core import main as core  # noqa: E402

results = []


def check(name, ok):
    results.append(bool(ok))
    print(("PASS  " if ok else "FAIL  ") + name)


T = tools.TOOLS
desktop = tmp / "apps"
desktop.mkdir()
for fname, name in (("google-chrome.desktop", "Google Chrome"), ("code.desktop", "Visual Studio Code"),
                    ("org.kde.konsole.desktop", "Konsole"), ("spotify.desktop", "Spotify")):
    (desktop / fname).write_text(f"[Desktop Entry]\nType=Application\nName={name}\nExec=x\n")

launched = []
with mock.patch.object(apps, "APP_DIRS", [desktop]), mock.patch.object(apps, "_apps", {"t": 0.0, "items": []}), \
        mock.patch.object(apps, "_launch", side_effect=launched.append), mock.patch.object(apps.shutil, "which", return_value="/usr/bin/x"):
    for said, want in (("the browser", "Google Chrome"), ("VS Code", "Visual Studio Code"), ("terminal", "Konsole"),
                       ("spotify", "Spotify"), ("Spotifi", "Spotify")):
        hit = apps.find_app(said)
        check(f"find {said!r}", hit and hit[0] == want)
    check("missing app is said plainly", apps.find_app("photoshop") is None)
    try:
        T["open_app"]["fn"]({"name": "photoshop"})
        check("open missing app raises", False)
    except tools.ToolError as e:
        check("open missing app raises", "could not find" in str(e))

    ids = ["{abc}"]
    closed = []
    with mock.patch.object(windows, "find_ids", return_value=ids), mock.patch.object(windows, "close", side_effect=closed.append):
        check("close asks first", T["close_app"]["risk"] == "confirm" and "Close Spotify" in T["close_app"]["describe"]({"name": "spotify"}))
        check("nothing closed before yes", closed == [])
        T["close_app"]["fn"]({"name": "spotify"})
        check("closed after the call", closed == [ids])
    with mock.patch.object(windows, "find_ids", return_value=[]):
        try:
            T["close_app"]["describe"]({"name": "spotify"})
            check("not open is said", False)
        except tools.ToolError as e:
            check("not open is said", "does not seem to be open" in str(e))
    got = []
    with mock.patch.object(windows, "find_ids", return_value=ids), mock.patch.object(windows, "activate", side_effect=got.append):
        T["switch_app"]["fn"]({"name": "chrome"})
    check("switch activates the first window", got == ["{abc}"])

ran = []
with mock.patch.object(apps.subprocess, "run", side_effect=lambda cmd, **k: ran.append(cmd) or mock.Mock(returncode=0)), \
        mock.patch.object(apps.shutil, "which", return_value="/usr/bin/brightnessctl"):
    T["brightness"]["fn"]({"text": "brightness up"})
    T["brightness"]["fn"]({"text": "set brightness to 40"})
    T["brightness"]["fn"]({"text": "dim the brightness by 20"})
check("brightness commands", ran == [["brightnessctl", "set", "10%+"], ["brightnessctl", "set", "40%"], ["brightnessctl", "set", "20%-"]])
with mock.patch.object(apps.shutil, "which", return_value=None):
    try:
        T["brightness"]["fn"]({"text": "brightness up"})
        check("missing brightnessctl said plainly", False)
    except tools.ToolError as e:
        check("missing brightnessctl said plainly", "brightnessctl" in str(e))

routes = {}
with mock.patch.object(core, "run_tool", side_effect=lambda a, b, c: routes.update(last=(a, b))), \
        mock.patch.object(core.browser, "ready", lambda: False):
    for text, want in (("close spotify", "close_app"), ("switch to chrome", "switch_app"), ("minimise this", "minimise_window"),
                       ("brightness down", "brightness"), ("open github.com", "open_site"), ("search python decorators", "web_search"),
                       ("open the folder resume", "open_path")):
        routes.clear()
        core.direct(text)
        check(f"{text!r} -> {want}", routes.get("last", [None])[0] == want)
    routes.clear()
    check("go to sleep is not a window command", not core.direct("go to sleep") and not routes)
    check("search my notes stays with notes", not (core.direct("search my notes for dsa") and routes.get("last", [""])[0] == "web_search"))
print("failures:", results.count(False))
sys.exit(1 if False in results else 0)
