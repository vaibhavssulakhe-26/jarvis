"""Checks the build, run, fix loop: a tiny Flask app is built in its own venv, started, fetched and stopped; broken code is repaired
(at most 4 times); unsafe code is refused. The brain is mocked; installing flask needs network (that part is skipped offline).
Run: python scripts/coder_build_check.py"""
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-build-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
(tmp / "run").mkdir()
os.environ["XDG_RUNTIME_DIR"] = str(tmp / "run")
os.environ["CODE_WORKSPACE"] = str(tmp / "work")
os.environ["GROQ_API_KEY"] = "gsk_test_secret_value_1234567890"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.actions import coder, procs  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def skip(name, why):
    print(f"skip {name}  ({why})")


T = tools.TOOLS
said = []
GOOD_FLASK = 'from flask import Flask\n\napp = Flask(__name__)\n\n\n@app.route("/")\ndef home():\n    return "Hello from Jarvis"\n'
patches = [mock.patch.object(coder.time, "sleep", lambda s: None), mock.patch.object(coder, "open_in_editor", return_value=None),
           mock.patch.object(core.voice, "say", lambda t: said.append(str(t))), mock.patch.object(coder.events, "emit"),
           mock.patch("jarvis.actions.screen.write_clip", lambda t: True)]
for p in patches:
    p.start()

# ---------------- Flask hello: build, install after yes, run, fetch, stop ----------------
calls = []


def flask_brain(prompt, max_tokens=0, system=None):
    calls.append(prompt)
    if "plan a small coding project" in (system or ""):
        return "name: hello flask\napp.py: the app\nrequirements.txt: packages"
    if "Write the file requirements.txt" in prompt:
        return "flask\n"
    return GOOD_FLASK


with mock.patch.object(brain, "code", side_effect=flask_brain):
    out = T["build_project"]["fn"]({"request": "build me a tiny flask hello app"})
folder = tmp / "work" / "hello-flask"
check("the project is a Flask app in its own folder under the workspace", (folder / "app.py").read_text() == GOOD_FLASK and coder.load_meta(folder)["kind"] == "flask")
check("the path is said in the reply", str(folder) in out, out)
check("it asks before installing anything", "Should I install" in out and "flask" in out and core.PENDING.get("action") == "install_deps", out)
check("nothing was installed before the yes", not (folder / ".venv").exists())

online = True
with mock.patch.object(brain, "code", side_effect=flask_brain):
    core.check_pending("yes")
if not (folder / ".venv" / "bin" / "python").exists() or any("install failed" in s.lower() or "could not set up" in s.lower() for s in said):
    online = False
    skip("install, run, fetch, stop", "pip could not install flask (offline?): " + " | ".join(said)[-200:])
else:
    check("yes creates the venv and installs flask", subprocess.run([str(folder / ".venv" / "bin" / "python"), "-c", "import flask"]).returncode == 0)
    check("the new project is checked by starting it", any("It runs" in s for s in said), str(said))
    check("the server is stopped after the check", not procs.alive())

    opened = []
    check("run asks first and says it starts in the background", T["run_project"]["risk"] == "confirm"
          and "background" in T["run_project"]["describe"]({}), T["run_project"]["describe"]({}))
    with mock.patch.object(coder, "open_web", lambda url: opened.append(url)):
        line = T["run_project"]["fn"]({})
    check("run it starts the app in the background and opens the browser", procs.alive() and len(opened) == 1 and "running" in line, line)
    body = urllib.request.urlopen(opened[0], timeout=5).read().decode()
    check("fetching the page returns the app's page", "Hello from Jarvis" in body, body)
    curl = subprocess.run(["curl", "-s", opened[0]], capture_output=True, text=True) if __import__("shutil").which("curl") else None
    check("curl gets the same page", curl is None or "Hello from Jarvis" in curl.stdout)
    port = int(opened[0].rsplit(":", 1)[1].strip("/"))
    with mock.patch.object(core.voice, "stop", lambda: True):
        core._handle("stop it")
    time.sleep(0.3)
    check("'stop it' kills the app", not procs.alive() and not procs.wait_port(port, None, 0.5), str(said[-1:]))
    check("and says so", any(s == "Stopped it." for s in said))

# ---------------- repair loop on a plain script ----------------
state_ = {"fixes": 0}


def script_brain(version):
    def fake(prompt, max_tokens=0, system=None):
        if "plan a small coding project" in (system or ""):
            return "name: fix demo\nmain.py: prints hello"
        if "Fix the problem" in prompt:
            state_["fixes"] += 1
            return version(state_["fixes"])
        return "print(undefined_name)\n"
    return fake


said.clear()
with mock.patch.object(brain, "code", side_effect=script_brain(lambda n: "print('hello from the fixed script')\n")):
    out = T["build_project"]["fn"]({"request": "build me a python script that says hello"})
check("a broken script is repaired and verified", "It runs after 1 fix" in out and state_["fixes"] == 1, out)
check("the repaired file is on disk", "fixed script" in (tmp / "work" / "fix-demo" / "main.py").read_text())

state_["fixes"] = 0
with mock.patch.object(brain, "code", side_effect=script_brain(lambda n: f"print(still_broken_{n})\n")):
    out = T["build_project"]["fn"]({"request": "build me a python script that never works"})
check("it gives up after exactly 4 fix attempts", state_["fixes"] == coder.MAX_FIXES == 4, str(state_["fixes"]))
check("and reports honestly what still fails", "still fails after 4 fixes" in out and "NameError" in out, out)
check("the log goes to the screen and clipboard, not into speech", "Last output" not in out and "Traceback" not in out)

state_["fixes"] = 0
with mock.patch.object(brain, "code", side_effect=script_brain(lambda n: "print(undefined_name)\n")):
    out = T["build_project"]["fn"]({"request": "build me a python script with no good fix"})
check("a fix that changes nothing stops the loop early", state_["fixes"] == 1 and "still fails" in out, f"{state_['fixes']} {out}")

# fix the last error from a failed run
proj = tmp / "work" / "run-fail"
proj.mkdir(parents=True)
(proj / "main.py").write_text("raise RuntimeError('boom')\n")
coder.save_meta(proj, {"kind": "script", "entry": "main.py", "request": "a demo"})
coder.last.update(dir=proj, main=proj / "main.py", error="")
with mock.patch.object(core.voice, "say"):
    line = T["run_project"]["fn"]({})
check("a failed run remembers its error", "RuntimeError" in coder.last["error"] and "fix the last error" in line, line)
with mock.patch.object(brain, "code", side_effect=lambda p, *a, **k: "print('ok now')\n"):
    out = T["fix_last_error"]["fn"]({})
check("fix the last error repairs the file and keeps a backup", "runs" in out and "ok now" in (proj / "main.py").read_text() and (proj / "main.py.bak").exists(), out)
coder.last["error"] = ""
(proj / ".run.log").unlink(missing_ok=True)
try:
    T["fix_last_error"]["fn"]({})
    check("with no error it says so", False)
except tools.ToolError as e:
    check("with no error it says so", "no recent error" in str(e))

# ---------------- environment and safety ----------------
leak = tmp / "work" / "leak"
leak.mkdir()
(leak / "main.py").write_text("import os\nprint('KEY=' + os.environ.get('GROQ_API_KEY', 'none'))\n")
coder.save_meta(leak, {"kind": "script", "entry": "main.py"})
ok, out, _ = coder.verify(leak, coder.load_meta(leak))
check("generated code never sees the API keys", ok and "KEY=none" in out and "gsk_test" not in out, out)

for name, code_ in (("sudo", "import os\nos.system('sudo ls')\n"), ("rm", "import os\nos.system('rm -rf /tmp/x')\n"), ("home", "import shutil, pathlib\nshutil.rmtree(pathlib.Path.home())\n")):
    d = tmp / "work" / f"unsafe-{name}"
    d.mkdir()
    (d / "main.py").write_text(code_)
    coder.save_meta(d, {"kind": "script", "entry": "main.py"})
    try:
        coder.verify(d, coder.load_meta(d))
        check(f"{name} in a project is never run", False)
    except tools.ToolError:
        check(f"{name} in a project is never run", True)
    try:
        coder.run_background(d, {"kind": "pyqt", "entry": "main.py"})
        check(f"{name} is not started in the background either", False)
    except tools.ToolError:
        check(f"{name} is not started in the background either", True)


def unsafe_brain(prompt, max_tokens=0, system=None):
    if "plan a small coding project" in (system or ""):
        return "name: bad one\nmain.py: x"
    return "import os\nos.system('sudo reboot')\n"


with mock.patch.object(brain, "code", side_effect=unsafe_brain):
    try:
        T["build_project"]["fn"]({"request": "build me a python script to reboot"})
        check("generated sudo code is refused before it is written", False)
    except tools.ToolError:
        check("generated sudo code is refused before it is written", not (tmp / "work" / "bad-one" / "main.py").exists())


def escape_brain(prompt, max_tokens=0, system=None):
    if "plan a small coding project" in (system or ""):
        return "name: escape\n../evil.py: x\n/etc/passwd: y\nmain.py: fine"
    return "print(1)\n"


with mock.patch.object(brain, "code", side_effect=escape_brain):
    T["build_project"]["fn"]({"request": "build me a python script that is fine"})
check("plan paths that climb out of the project are dropped", not (tmp / "work" / "evil.py").exists() and (tmp / "work" / "escape" / "main.py").exists())
try:
    coder.write_project_file(tmp / "work" / "escape", "../../outside.txt", "x")
    check("writing outside the workspace is impossible", False)
except tools.ToolError:
    check("writing outside the workspace is impossible", not (tmp / "outside.txt").exists())
try:
    coder.write_project_file(tmp / "elsewhere", "a.py", "x")
    check("a project folder outside the workspace is refused", False)
except tools.ToolError:
    check("a project folder outside the workspace is refused", True)

# package approval: only plain names, installed only in the project venv
evil = tmp / "work" / "evil-reqs"
evil.mkdir()
(evil / "requirements.txt").write_text("flask\n--index-url http://evil.example/simple\ngit+https://example.com/x.git\n-r other.txt\nrequests>=2.0  # ok\n")
good, rejected = coder.requirements(evil)
check("requirements keep plain names and reject options and URLs", good == ["flask", "requests>=2.0"] and len(rejected) == 3, f"{good} {rejected}")
coder.save_meta(evil, {"kind": "flask", "entry": "app.py"})
try:
    T["install_deps"]["fn"]({"project": str(evil)})
    check("install_deps refuses a requirements file with options", False)
except tools.ToolError as e:
    check("install_deps refuses a requirements file with options", "will not install" in str(e))
try:
    T["install_deps"]["fn"]({"project": "/etc"})
    check("install_deps refuses folders outside the workspace", False)
except tools.ToolError:
    check("install_deps refuses folders outside the workspace", True)
(leak / "helper.py").write_text("x = 1\n")
check("an unapproved package is reported, not installed", coder.missing_package("ModuleNotFoundError: No module named 'numpy'", leak) == "numpy"
      and coder.missing_package("No module named 'json'", leak) == "" and coder.missing_package("No module named 'helper'", leak) == "")

# ---------------- other project kinds ----------------
check("project kinds are detected", [coder.detect_kind(x) for x in ("a flask api", "a FastAPI service", "a pyqt notes app", "a portfolio website", "a web app for todos", "a calculator")]
      == ["flask", "fastapi", "pyqt", "static", "flask", "script"])
html = tmp / "work" / "site"
html.mkdir()
(html / "index.html").write_text('<html><link href="style.css"><script src="script.js"></script></html>')
coder.save_meta(html, {"kind": "static", "entry": "index.html"})
ok, out, hint = coder.verify(html, coder.load_meta(html))
check("a static page that refers to a missing file fails with that file named", not ok and hint == "style.css", f"{out} {hint}")
(html / "style.css").write_text("body{}")
(html / "script.js").write_text("let x = ;")
ok, out, hint = coder.verify(html, coder.load_meta(html))
check("a JavaScript syntax error is caught", (not ok and hint == "script.js") if __import__("shutil").which("node") else True, f"{out} {hint}")
(html / "script.js").write_text("let x = 1;")
check("a good static page passes", coder.verify(html, coder.load_meta(html))[0])

qt = tmp / "work" / "qtapp"
qt.mkdir()
(qt / "main.py").write_text("import sys\nfrom PyQt6.QtWidgets import QApplication, QLabel\napp = QApplication(sys.argv)\nw = QLabel('hi')\nw.show()\nsys.exit(app.exec())\n")
coder.save_meta(qt, {"kind": "pyqt", "entry": "main.py"})
ok, out, _ = coder.verify(qt, coder.load_meta(qt))
check("a PyQt app is started offscreen and left running", ok, out)

# ---------------- add a feature, explain, git init ----------------
site_brain_calls = []


def site_brain(prompt, max_tokens=0, system=None):
    site_brain_calls.append(prompt)
    if "plan a change" in (system or ""):
        return "script.js: add a counter"
    return "let counter = 0;\n"


coder.last.update(dir=html, main=html / "index.html")
with mock.patch.object(brain, "code", side_effect=site_brain):
    out = T["add_feature"]["fn"]({"feature": "a click counter", "project": "site"})
check("add a feature changes the planned file with a backup", (html / "script.js").read_text() == "let counter = 0;\n" and (html / "script.js.bak").exists(), out)
check("and tests the project again", "It runs" in out, out)
try:
    T["add_feature"]["fn"]({"feature": "x", "project": "no such thing"})
    check("an unknown project is refused", False)
except tools.ToolError:
    check("an unknown project is refused", True)
with mock.patch.object(brain, "code", return_value="It starts a Qt window with one label. Nothing else."):
    check("explain this file is a short spoken answer", T["explain_file"]["fn"]({"file": str(qt / "main.py")}).startswith("It starts a Qt window"))

if __import__("shutil").which("git"):
    r = T["git_init_project"]["fn"]({"project": "site"})
    remotes = subprocess.run(["git", "remote"], cwd=html, capture_output=True, text=True).stdout.strip()
    check("git init makes a local repository only", (html / ".git").is_dir() and remotes == "" and "no remote" in r, r)
    check("it adds a .gitignore and commits nothing", (html / ".gitignore").exists() and subprocess.run(["git", "log"], cwd=html, capture_output=True).returncode != 0)
    check("a second git init says so", "already" in T["git_init_project"]["fn"]({"project": "site"}))
else:
    skip("git init", "git is not installed")

# ---------------- children die with Jarvis ----------------
log = tmp / "sleep.log"
proc = procs.spawn("sleeper", ["sleep", "60"], tmp, procs.clean_env(), log)
grandchild = procs.spawn("sh", ["sh", "-c", "sleep 60 & wait"], tmp, procs.clean_env(), log)
check("tracked children are running", procs.alive("sleeper") and procs.alive("sh"))
procs.stop_all()
check("stop_all kills them and their children", proc.poll() is not None and grandchild.poll() is not None and not procs.alive())
check("the cleanup is registered for exit", "atexit.register(stop_all)" in Path(procs.__file__).read_text())

# ---------------- routing ----------------
ran = []
cases = (("fix the last error", "fix_last_error"), ("explain this file", "explain_file"), ("explain main.py", "explain_file"),
         ("git init this project", "git_init_project"), ("run it", "run_project"), ("add dark mode to site", "add_feature"))
for phrase, name in cases:
    with mock.patch.object(core, "run_tool", lambda a, args, s: ran.append(a)), mock.patch.object(core.brain, "think", side_effect=AssertionError("brain")):
        core.direct(phrase)
    check(f"{phrase!r} -> {name}", ran and ran[-1] == name, str(ran[-1:]))
del ran[:]
with mock.patch.object(core, "run_tool", lambda a, args, s: ran.append(a)):
    core.direct("add milk to my shopping list")
check("ordinary 'add X to my list' is not taken for a project", "add_feature" not in ran, str(ran))

for p in patches:
    p.stop()
procs.stop_all()
sys.exit(1 if bad else 0)
