"""Small coding helper: build a project one file per call, edit a file, find bugs, run the result.
Everything is written inside the workspace folder; changes to existing files wait for a spoken yes."""
import difflib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..brain import brain
from ..core import config
from . import events, procs
from .tools import ToolError, _launch, tool

WORKSPACE = Path(config.get("CODE_WORKSPACE") or "~/Projects/jarvis-builds").expanduser()
MAX_FILES = 5
MAX_FIXES = 4
SERVER_WAIT = 20
QT_SECONDS = 4
PROJECT = "project"
MAX_CHARS = 20000
FILE_TOKENS = 2000
RUN_SECONDS = 20
GAP = 1.5
PLAN_SYSTEM = ("You plan a small coding project. Reply with a line 'name: <two or three word folder name>' then one "
               "line per file as 'path: what it does'. Use at most {n} files, no folders deeper than one level, "
               "and no other text.")
FILE_SYSTEM = ("You write one source file. Reply with only the complete file content: no explanations and no "
               "markdown fences. Keep it short, working and self-contained.")
EDIT_SYSTEM = ("You change one source file as asked. Reply with only the complete new file content: no "
               "explanations and no markdown fences. Change as little as possible.")
BUG_SYSTEM = ("You fix a bug. Reply in this exact form:\nCAUSE: <one or two short spoken sentences>\nFIXED:\n"
              "<the corrected version of the given lines only, no fences>")
KIND_NOTES = {
    "script": "A Python script using only the standard library. It prints a short result and exits. Put a test in test_main.py with unittest only if it is simple.",
    "flask": "A Flask app. app.py defines `app = Flask(__name__)` at module level and never calls app.run. requirements.txt lists flask only. "
             "The / route returns the main page.",
    "fastapi": "A FastAPI app. app.py defines `app = FastAPI()` at module level. requirements.txt lists fastapi and uvicorn. GET / answers.",
    "static": "A static site: index.html, style.css and script.js. No build step and no external CDN or network calls.",
    "pyqt": "A small PyQt6 desktop app. main.py builds a QApplication and one window, and starts the event loop only under if __name__ == '__main__'.",
}
REQUIRED = {"script": ["main.py"], "flask": ["app.py", "requirements.txt"], "fastapi": ["app.py", "requirements.txt"],
            "static": ["index.html"], "pyqt": ["main.py"]}
ENTRY = {"script": "main.py", "flask": "app.py", "fastapi": "app.py", "static": "index.html", "pyqt": "main.py"}
VENV_KINDS = ("flask", "fastapi")
SERVER_KINDS = ("flask", "fastapi")
UNSAFE = re.compile(r"\bsudo\b|\brm\s+-\w*[rf]\w*[ \t]|\bmkfs\b|\bdd\s+if=|:\(\)\s*\{|chmod\s+-R\b|"
                    r"rmtree\(\s*(?:['\"][/~]|os\.path\.expanduser|(?:pathlib\.)?Path\.home)")
PACKAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(?:\[[A-Za-z0-9,._-]+\])?(?:\s*(?:==|>=|<=|~=|!=|>|<)\s*[A-Za-z0-9.*+!-]+)?$")
FEATURE_PLAN = ("You plan a change to a small project. Reply with one line per file to change or create, as 'path: what to do', "
                "at most 3 files, no folders deeper than one level, and no other text.")
last = {"dir": None, "main": None, "error": ""}
edit = {}


def _fence(text):
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip("\n") + "\n"


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:30] or "project"


def inside(path, root=None):
    try:
        Path(path).resolve().relative_to((root or WORKSPACE).resolve())
        return True
    except ValueError:
        return False


def open_in_editor(path):
    for exe in ("code", "codium", "antigravity"):
        if shutil.which(exe):
            _launch([exe, str(path)])
            return "VS Code" if exe == "code" else exe
    if shutil.which("xdg-open"):
        _launch(["xdg-open", str(path)])
        return "your default app"
    return None


def parse_plan(reply, request):
    name, files = "", []
    for line in reply.splitlines():
        m = re.match(r"^\W*(name|[\w./-]+\.\w{1,5})\s*:\s*(.*)$", line.strip(), re.I)
        if not m:
            continue
        if m.group(1).lower() == "name":
            name = m.group(2)
        else:
            rel = m.group(1).lstrip("./")
            if rel.count("/") <= 1 and not rel.startswith(".") and ".." not in rel:
                files.append((rel, m.group(2).strip()))
    if not files:
        page = re.search(r"\b(html|web ?site|web ?page|portal|landing)\b", request, re.I)
        files = [("index.html" if page else "main.py", request)]
    return name or request, files[:MAX_FILES]


def main_file(files):
    for rel, _ in files:
        if Path(rel).name in ("index.html", "main.py", "app.py", "main.js"):
            return rel
    return files[0][0]


def detect_kind(request):
    t = str(request).lower()
    if re.search(r"\bfastapi\b", t):
        return "fastapi"
    if re.search(r"\bflask\b", t):
        return "flask"
    if re.search(r"\b(pyqt\d*|pyside\d*|qt app|desktop app|gui|window app)\b", t):
        return "pyqt"
    if re.search(r"\b(html|websites?|web ?sites?|web ?pages?|landing|portfolio|static|javascript)\b", t):
        return "static"
    if re.search(r"\b(web ?app|api|server|backend|dashboard)\b", t):
        return "flask"
    return "script"


def ensure_required(kind, files, request):
    have = {rel for rel, _ in files}
    extra = [(rel, request if rel != "requirements.txt" else "the packages it needs, one per line")
             for rel in REQUIRED[kind] if rel not in have]
    return (extra + files)[:MAX_FILES] if len(files) + len(extra) > MAX_FILES else files + extra


def meta_path(folder):
    return Path(folder) / ".jarvis.json"


def load_meta(folder):
    try:
        data = json.loads(meta_path(folder).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_meta(folder, meta):
    meta_path(folder).write_text(json.dumps(meta, indent=1))


def py_for(folder):
    venv = Path(folder) / ".venv" / "bin" / "python"
    return str(venv) if venv.exists() else sys.executable


def source_files(folder):
    return [p for p in sorted(Path(folder).rglob("*")) if p.is_file() and ".venv" not in p.parts and "__pycache__" not in p.parts
            and p.suffix in (".py", ".js", ".sh", ".html", ".css", ".txt", ".md", ".json") and p.name != ".jarvis.json"
            and not p.name.endswith(".bak")]


def unsafe_files(folder):
    """Source files holding something I will never run: sudo, rm -rf and similar."""
    out = []
    for p in source_files(folder):
        if p.suffix in (".py", ".js", ".sh") and UNSAFE.search(p.read_text(errors="ignore")):
            out.append(p.name)
    return out


def write_project_file(folder, rel, body, backup=False):
    """Write inside the project folder only; a changed existing file keeps one .bak."""
    target = Path(folder) / rel
    if Path(rel).is_absolute() or ".." in Path(rel).parts or not inside(target, folder) or not inside(target):
        raise ToolError("I only write inside the code workspace.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if backup and target.exists():
        bak = Path(str(target) + ".bak")
        if not bak.exists():
            shutil.copy2(target, bak)
    target.write_text(body[:MAX_CHARS])


def requirements(folder):
    """(valid package specs, rejected lines) from requirements.txt. Options, URLs and paths are rejected."""
    good, rejected = [], []
    try:
        lines = (Path(folder) / "requirements.txt").read_text().splitlines()
    except OSError:
        return [], []
    for line in lines:
        line = line.split("#")[0].strip()
        if not line:
            continue
        (good if PACKAGE.match(line) else rejected).append(line)
    return good, rejected


def needs_install(folder, meta):
    if meta.get("kind") not in VENV_KINDS:
        return []
    pkgs, _ = requirements(folder)
    if pkgs and (not (Path(folder) / ".venv" / "bin" / "python").exists() or sorted(meta.get("installed", [])) != sorted(pkgs)):
        return pkgs
    return []


def top_module(name):
    return re.sub(r"[^a-z0-9]", "", name.split("[")[0].split("=")[0].split("<")[0].split(">")[0].split("~")[0].split("!")[0].lower())


def missing_package(output, folder):
    """A third-party module the program wants that nobody approved (not stdlib, not a local file, not in requirements)."""
    m = re.search(r"No module named '([\w.]+)'", output)
    if not m:
        return ""
    top = m.group(1).split(".")[0]
    if top in sys.stdlib_module_names or (Path(folder) / (top + ".py")).exists() or (Path(folder) / top).is_dir():
        return ""
    return top


def error_target(folder, output, meta):
    for m in reversed(list(re.finditer(r'File "([^"]+)", line \d+|(/[^\s:]+\.(?:js|py)):\d+', output))):
        p = Path(m.group(1) or m.group(2))
        if p.is_file() and inside(p, folder):
            return str(p.resolve().relative_to(Path(folder).resolve()))
    return meta.get("entry") or ENTRY.get(meta.get("kind"), "main.py")


def fix_once(folder, meta, output, request, hint=None, backup=False):
    """One model call to repair the file the error points at. Returns the file name, or None if nothing changed."""
    rel = hint or error_target(folder, output, meta)
    target = Path(folder) / rel
    listing = ", ".join(str(p.relative_to(folder)) for p in source_files(folder))
    if not target.exists():
        text = brain.code(f"Project: {request}\nFiles in the project: {listing}\n\nWrite the missing file {rel}.", FILE_TOKENS,
                          system=FILE_SYSTEM + " " + KIND_NOTES.get(meta.get("kind"), ""))
        old = ""
    else:
        old = target.read_text(errors="ignore")
        if len(old) > MAX_CHARS:
            return None
        text = brain.code(f"Project: {request}\nFile {rel}:\n{old}\n\nRunning it failed with:\n{output[-1800:]}\n\nFix the problem.",
                          FILE_TOKENS, system=EDIT_SYSTEM + " " + KIND_NOTES.get(meta.get("kind"), ""))
    if not text:
        return None
    body = _fence(text)
    if body.strip() == old.strip() or UNSAFE.search(body):
        return None
    write_project_file(folder, rel, body, backup)
    return rel


def _run_py(folder, args, seconds, **env):
    return subprocess.run([py_for(folder)] + args, cwd=folder, env=procs.clean_env(**env), capture_output=True, text=True,
                          timeout=seconds, stdin=subprocess.DEVNULL)


def _combined(r):
    return ((r.stdout or "") + (r.stderr or "")).strip()


def start_server(folder, meta):
    """Launch the project's web server on a free port, output to .run.log. Returns (port, process)."""
    port = procs.free_port()
    py = py_for(folder)
    if meta["kind"] == "flask":
        cmd = [py, "-m", "flask", "--app", "app", "run", "--port", str(port), "--no-reload"]
    else:
        cmd = [py, "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)]
    log = Path(folder) / ".run.log"
    log.write_text("")
    proc = procs.spawn(PROJECT, cmd, folder, procs.clean_env(PORT=port, PYTHONUNBUFFERED=1), log)
    return port, proc


def fetch_status(port, path="/"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except (OSError, ValueError):
        return 0


def verify(folder, meta):
    """Run or test the project. Returns (ok, output, file to rewrite or None). Raises ToolError for code I will not run."""
    bad = unsafe_files(folder)
    if bad:
        raise ToolError(f"{bad[0]} has something I will not run, like sudo or rm -rf, so I stopped.")
    kind = meta.get("kind", "script")
    entry = meta.get("entry") or ENTRY.get(kind, "main.py")
    if not (Path(folder) / entry).is_file():
        return False, f"{entry} is missing.", entry
    if kind == "static":
        page = (Path(folder) / "index.html").read_text(errors="ignore")
        if not page.strip():
            return False, "index.html is empty.", "index.html"
        for ref in re.findall(r"""(?:src|href)=["']([^"'#:?]+)["']""", page):
            if not (Path(folder) / ref).is_file():
                return False, f"index.html refers to {ref}, which does not exist.", ref
        if shutil.which("node"):
            for js in sorted(Path(folder).glob("*.js")):
                r = subprocess.run(["node", "--check", str(js)], capture_output=True, text=True, timeout=30)
                if r.returncode:
                    return False, r.stderr.strip(), js.name
        return True, "The page and the files it uses are there.", None
    if kind in SERVER_KINDS:
        port, proc = start_server(folder, meta)
        try:
            if not procs.wait_port(port, proc, SERVER_WAIT):
                return False, procs.tail(Path(folder) / ".run.log") or "The server did not start.", None
            code = fetch_status(port)
            if code == 0 or code >= 500:
                return False, f"GET / answered {code or 'nothing'}.\n" + procs.tail(Path(folder) / ".run.log"), None
            return True, f"The server answered {code} on /.", None
        finally:
            procs.stop(PROJECT)
    if kind == "pyqt":
        for src in sorted(Path(folder).glob("*.py")):
            r = _run_py(folder, ["-m", "py_compile", str(src)], 30)
            if r.returncode:
                return False, _combined(r), src.name
        try:
            r = _run_py(folder, [entry], QT_SECONDS, QT_QPA_PLATFORM="offscreen")
        except subprocess.TimeoutExpired:
            return True, "The window opened and kept running.", None
        return (True, "It started and exited cleanly.", None) if r.returncode == 0 else (False, _combined(r), None)
    try:
        r = _run_py(folder, [entry], RUN_SECONDS)
    except subprocess.TimeoutExpired:
        return True, f"It was still running after {RUN_SECONDS} seconds.", None
    if r.returncode:
        return False, _combined(r), None
    tests = sorted(Path(folder).glob("test_*.py"))
    if tests:
        t = _run_py(folder, ["-m", "unittest", "discover", "-s", ".", "-p", "test_*.py"], RUN_SECONDS)
        if t.returncode:
            return False, _combined(t), None
    return True, (r.stdout or "").strip() or "It ran and printed nothing.", None


def check_and_fix(folder, meta, request, log, backup=False):
    """Verify, and on failure repair and verify again, at most MAX_FIXES times. Returns (ok, fixes made, last output)."""
    out, fixes = "", 0
    for attempt in range(MAX_FIXES + 1):
        ok, out, hint = verify(folder, meta)
        log.append(f"check {attempt + 1}: " + ("ok" if ok else (out.strip().splitlines() or ["failed"])[-1][:200]))
        if ok:
            last["error"] = ""
            return True, fixes, out
        last["error"] = out
        missing = missing_package(out, folder)
        if missing:
            log.append(f"stopped: it needs the package {missing}, which was not approved")
            return False, fixes, out + f"\nIt needs the package {missing}, which is not installed and was not on the list you approved."
        if attempt == MAX_FIXES:
            break
        time.sleep(GAP)
        rel = fix_once(folder, meta, out, request, hint, backup)
        if not rel:
            log.append("stopped: the model gave no usable fix")
            break
        fixes += 1
        log.append(f"fix {fixes}: rewrote {rel}")
    return False, fixes, out


def report(folder, ok, fixes, out, log, count=None):
    """One spoken sentence or two; the whole log goes to the screen and the clipboard."""
    full = "\n".join(log) + ("" if ok else "\n\nLast output:\n" + out[-1500:])
    events.emit("sys", full)
    from .screen import write_clip
    write_clip(full)
    head = f"Built {count} file{'s' if count != 1 else ''} in {Path(folder).name}, saved at {folder}." if count else f"Updated {Path(folder).name}, saved at {folder}."
    if ok:
        return head + (" It runs." if not fixes else f" It runs after {fixes} fix{'es' if fixes != 1 else ''}.")
    line = (out.strip().splitlines() or ["no output"])[-1][:140]
    return head + f" It still fails after {fixes} fix{'es' if fixes != 1 else ''}: {line}. The full log is on your screen and copied."


def ask_install(folder, pkgs):
    from ..core import main as core
    core.PENDING.clear()
    core.PENDING.update({"action": "install_deps", "args": {"project": str(folder)}, "until": time.time() + 60})
    return f"It needs {', '.join(pkgs)}. Should I install that in the project's own virtual environment? Say yes."


def complete(folder, meta, request, count=None, backup=False):
    """After files are written: ask before installing packages, otherwise verify and report."""
    pkgs = needs_install(folder, meta)
    if pkgs:
        head = f"Built {count} files in {Path(folder).name}, saved at {folder}. " if count else f"Updated {Path(folder).name}, saved at {folder}. "
        return head + ask_install(folder, pkgs)
    log = [f"project {Path(folder).name} ({meta.get('kind')})"]
    ok, fixes, out = check_and_fix(folder, meta, request, log, backup)
    line = report(folder, ok, fixes, out, log, count)
    opened = open_in_editor(Path(folder) / (meta.get("entry") or ENTRY.get(meta.get("kind"), "")))
    return line + (f" Opened in {opened}." if opened else "")


VAGUE_WORDS = {"build", "create", "make", "write", "me", "a", "an", "some", "the", "something", "anything", "cool", "nice", "new", "small", "simple",
               "python", "code", "program", "app", "apps", "application", "project", "thing", "stuff", "website", "web", "site", "page", "script",
               "please", "for", "my", "i", "want", "to", "you", "can", "could", "flask", "fastapi", "pyqt", "html", "javascript", "good", "awesome",
               "it", "one", "of", "any", "kind", "sort", "something", "interesting", "fun", "useful", "software", "tool", "desktop", "gui", "and"}
_asking = {"until": 0.0}
ASK_SPEC = "What should it do? For example, a flask app that shows the time, or a python script that renames my files."


def is_vague(request):
    words = re.findall(r"[a-z]+", str(request).lower())
    return not [w for w in words if w not in VAGUE_WORDS]


def asking():
    return time.time() < _asking["until"]


def take_spec(text):
    """After the build question, the next sentence is the spec. Returns it, or None if no question is open or it is not an answer."""
    if time.time() > _asking["until"]:
        return None
    _asking["until"] = 0.0
    t = " ".join(str(text).split()).strip(" .")
    if not t or is_vague(t) or re.match(r"^(?:no|never mind|cancel|stop|forget it)\b", t, re.I):
        return None
    return t


@tool("build_project", 'args {"request": "<what to build, in words>"} - build a small project (Python script, Flask or FastAPI app, static web page, PyQt app): plan the files, write them in the code workspace, run them and fix errors; for "build me a ...", "create a ...", "write a ..."')
def build_project(args):
    request = str(args.get("request") or "").strip()
    if not request or is_vague(request):
        _asking["until"] = time.time() + 45
        raise ToolError(ASK_SPEC)
    kind = detect_kind(request)
    note = KIND_NOTES[kind]
    plan = brain.code(f"Project: {request}", 300, system=PLAN_SYSTEM.format(n=MAX_FILES) + " " + note)
    name, files = parse_plan(plan, request)
    files = ensure_required(kind, files, request)
    WORKSPACE.mkdir(parents=True, exist_ok=True)
    folder = WORKSPACE / _slug(name)
    n = 2
    while folder.exists():
        folder = WORKSPACE / f"{_slug(name)}-{n}"
        n += 1
    outline = "\n".join(f"- {rel}: {what}" for rel, what in files)
    written = []
    for i, (rel, what) in enumerate(files):
        if i:
            time.sleep(GAP)
        prompt = (f"Project: {request}\nFiles in the project:\n{outline}\n\nWrite the file {rel}: {what}"
                  + (f"\nThe other files already written: {', '.join(written)}" if written else ""))
        text = brain.code(prompt, FILE_TOKENS, system=FILE_SYSTEM + " " + note)
        if not text:
            if not written:
                raise ToolError("I could not write that right now. Try again in a minute.")
            break
        body = _fence(text)
        if UNSAFE.search(body):
            raise ToolError(f"The code for {rel} had something I will not write, like sudo or rm -rf, so I stopped.")
        write_project_file(folder, rel, body)
        written.append(rel)
    entry = ENTRY[kind] if ENTRY[kind] in written else main_file([(w, "") for w in written])
    meta = {"kind": kind, "entry": entry, "request": request[:300], "count": len(written)}
    save_meta(folder, meta)
    last.update(dir=folder, main=folder / entry, error="")
    return complete(folder, meta, request, len(written))


@tool("install_deps", "args {\"project\": \"<folder>\"} - create the project's own virtual environment and install the packages in its requirements file; only after the user said yes")
def install_deps(args):
    folder = Path(args.get("project") or last["dir"] or "")
    if not folder.is_dir() or not inside(folder):
        raise ToolError("I only install packages for projects in the code workspace.")
    meta = load_meta(folder)
    pkgs, rejected = requirements(folder)
    if rejected:
        raise ToolError(f"requirements.txt has a line I will not install: {rejected[0][:60]}.")
    if not pkgs:
        raise ToolError("That project has no packages to install.")
    venv = folder / ".venv"
    try:
        if not (venv / "bin" / "python").exists():
            subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True, capture_output=True, timeout=120)
        r = subprocess.run([str(venv / "bin" / "python"), "-m", "pip", "install", "--disable-pip-version-check", "-q"] + pkgs,
                           cwd=folder, env=procs.clean_env(), capture_output=True, text=True, timeout=400)
    except (subprocess.SubprocessError, OSError) as e:
        raise ToolError(f"I could not set up the environment: {type(e).__name__}.")
    if r.returncode:
        raise ToolError("The install failed: " + ((r.stderr or "").strip().splitlines() or ["unknown error"])[-1][:140])
    meta["installed"] = pkgs
    save_meta(folder, meta)
    last.update(dir=folder, main=folder / (meta.get("entry") or ""), error="")
    return complete(folder, meta, meta.get("request", ""), meta.get("count"))


def resolve(raw):
    """A file path from a spoken name: a path, a file in the last build, or one in the workspace."""
    raw = str(raw or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_absolute() and p.is_file():
            return p
        if last["dir"] and (Path(last["dir"]) / raw).is_file():
            return Path(last["dir"]) / raw
        if WORKSPACE.is_dir():
            hit = next((h for h in WORKSPACE.rglob(Path(raw).name) if h.is_file()), None)
            if hit:
                return hit
    elif last["main"] and Path(last["main"]).is_file():
        return Path(last["main"])
    return None


def locate(raw, then):
    path = resolve(raw)
    if path:
        return path
    from .documents import locate as find
    return find(raw, then)


def diff_summary(old, new):
    a, b = old.splitlines(), new.splitlines()
    added = removed = 0
    first = ""
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b).get_opcodes():
        if tag == "equal":
            continue
        added += j2 - j1
        removed += i2 - i1
        if not first and j2 > j1:
            first = b[j1].strip()[:60]
    line = f"{added} lines added and {removed} removed"
    return line + (f", starting with {first}" if first else "")


def stage(path, new, then_say):
    """Hold a change until the user says yes, using the shared yes or no question."""
    from ..core import main as core
    old = path.read_text(errors="ignore")
    if new.strip() == old.strip():
        return "That would not change anything."
    edit.clear()
    edit.update(path=path, new=new)
    core.PENDING.clear()
    core.PENDING.update({"action": "apply_edit", "args": {}, "until": time.time() + 60})
    where = "" if inside(path) else " It is outside your workspace. "
    return f"{then_say} {diff_summary(old, new)}.{where} Should I apply it? I keep a backup."


@tool("apply_edit", "args {} - apply the change that was just described; only after the user said yes")
def apply_edit(args):
    if not edit:
        raise ToolError("There is no change waiting.")
    path, new = edit["path"], edit["new"]
    edit.clear()
    shutil.copy2(path, str(path) + ".bak")
    path.write_text(new)
    return f"Done. The old version is saved as {path.name}.bak."


@tool("edit_file", 'args {"file": "<file name or path>", "change": "<what to change or add>"} - change a code file after showing a summary and getting a yes; for "edit X", "add Y to file Z"')
def edit_file(args):
    change = str(args.get("change") or "").strip()
    if not change:
        raise ToolError("What should I change?")
    path = locate(args.get("file"), ("edit_file", {"change": change}))
    old = path.read_text(errors="ignore")
    if len(old) > MAX_CHARS:
        raise ToolError("That file is too big for me to edit in one go.")
    text = brain.code(f"File {path.name}:\n{old}\n\nChange to make: {change}", FILE_TOKENS, system=EDIT_SYSTEM)
    if not text:
        raise ToolError("I could not work on that right now. Try again in a minute.")
    return stage(path, _fence(text), "Here is the change.")


def check(path):
    """The compiler or linter output for a file, empty when it is clean. Raises ToolError for other languages."""
    ext = Path(path).suffix.lower()
    if ext == ".py":
        r = subprocess.run([sys.executable, "-m", "py_compile", str(path)], capture_output=True, text=True, timeout=30)
        out = r.stderr
        if r.returncode == 0:
            lint = subprocess.run([sys.executable, "-m", "pyflakes", str(path)], capture_output=True, text=True, timeout=30)
            out = lint.stdout if "No module named" not in lint.stderr else ""
        return out.strip()
    if ext in (".js", ".mjs") and shutil.which("node"):
        r = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True, timeout=30)
        return r.stderr.strip() if r.returncode else ""
    raise ToolError("I can check Python files, and JavaScript when node is installed.")


def error_window(output, lines):
    nums = [int(n) for n in re.findall(r"(?:line |\.py:|\.js:)(\d+)", output)]
    if not nums:
        return 0, min(len(lines), 40)
    return max(0, min(nums) - 6), min(len(lines), max(nums) + 5)


@tool("find_bugs", 'args {"file": "<file name, or clipboard>"} - check a Python or JavaScript file (or the code on the clipboard) for errors and offer a fix; for "find bugs in X", "debug X", "fix X"')
def find_bugs(args):
    raw = str(args.get("file") or "").strip()
    from .screen import read_clip, write_clip
    if not raw or raw.lower() in ("clipboard", "my clipboard", "the clipboard", "the code on my clipboard"):
        text = read_clip()
        if not text:
            raise ToolError("Your clipboard is empty.")
        from . import clipwatch, debug
        if clipwatch.ERROR.search(text):
            return debug.debug_clipboard({"kind": "error"})
        scratch = config.runtime_file("clip_check" + (".js" if re.search(r"\b(const|let|function)\b|=>", text) else ".py"))
        scratch.write_text(text)
        path, from_clip = scratch, True
    else:
        path, from_clip = locate(raw, ("find_bugs", {})), False
    try:
        output = check(path)
        if not output:
            return f"I found no errors in {'the clipboard code' if from_clip else path.name}."
        lines = path.read_text(errors="ignore").splitlines()
        a, b = error_window(output, lines)
        snippet = "\n".join(lines[a:b])
        reply = brain.code(f"Errors:\n{output[:1200]}\n\nLines {a + 1} to {b}:\n{snippet}", 800, system=BUG_SYSTEM)
        cause, _, fixed = reply.partition("FIXED:")
        cause = cause.replace("CAUSE:", "").strip()
        if not cause or not fixed.strip():
            raise ToolError("I found an error but could not work out the fix right now.")
        new_lines = lines[:a] + _fence(fixed).splitlines() + lines[b:]
        new = "\n".join(new_lines) + "\n"
        probe = path.with_name("probe_" + path.name)
        probe.write_text(new)
        try:
            still = check(probe)
        finally:
            probe.unlink(missing_ok=True)
        if still and len(still.splitlines()) >= len(output.splitlines()):
            return cause + " I could not make a clean fix for it."
        if from_clip:
            write_clip(new)
            return cause + " The fixed code is on your clipboard."
        return stage(path, new, cause)
    finally:
        if from_clip:
            path.unlink(missing_ok=True)


def run_target(args):
    path = resolve(args.get("file"))
    if path is None:
        raise ToolError("I have nothing to run yet. Build something first.")
    if not inside(path):
        raise ToolError("I only run files inside the code workspace.")
    if path.suffix.lower() not in (".py", ".js"):
        raise ToolError("I can run Python and JavaScript files. Open web pages in the browser instead.")
    if re.search(r"\bsudo\b", path.read_text(errors="ignore")):
        raise ToolError("That file uses sudo, so I will not run it.")
    return path


def find_project(name):
    """A project folder in the workspace from a spoken name, or the last build for 'it' and 'this'. None if there is no match."""
    raw = str(name or "").strip().lower()
    if raw in ("", "it", "this", "that", "this project", "the project", "last", "the last one") or raw.startswith("the last"):
        return Path(last["dir"]) if last["dir"] and Path(last["dir"]).is_dir() else None
    if not WORKSPACE.is_dir():
        return None
    slug = _slug(re.sub(r"^(?:the|my)\s+", "", raw))
    dirs = {p.name: p for p in WORKSPACE.iterdir() if p.is_dir() and not p.name.startswith(".")}
    if slug in dirs:
        return dirs[slug]
    part = [n for n in dirs if slug in n or n in slug]
    if len(part) == 1:
        return dirs[part[0]]
    close = difflib.get_close_matches(slug, list(dirs), 1, 0.75)
    return dirs[close[0]] if close else None


def project_of(args):
    """The project folder a run or fix request means, if it is one of ours (has a .jarvis.json)."""
    raw = str(args.get("file") or args.get("project") or "").strip()
    folder = None
    if raw:
        path = resolve(raw)
        if path:
            meta = load_meta(path.parent)
            folder = path.parent if meta.get("kind") and path.name == meta.get("entry") else None
        else:
            folder = find_project(raw)
    elif last["dir"]:
        folder = Path(last["dir"])
    return folder if folder and inside(folder) and load_meta(folder).get("kind") else None


def web_url(port):
    return f"http://127.0.0.1:{port}/"


def open_web(url):
    """The Playwright browser when it is set up, otherwise the normal browser."""
    try:
        from . import browser
        if browser.ready():
            return browser.open_page(url)
    except Exception:
        pass
    from .tools import _browser
    _browser(url)


def _describe_run(args):
    folder = project_of(args)
    if folder:
        meta = load_meta(folder)
        if meta["kind"] in SERVER_KINDS + ("pyqt", "static"):
            return f"Start {folder.name} ({meta['kind']}) in the background?"
    path = run_target(args)
    return f"Run {path.name} from {path.parent.name} for up to {RUN_SECONDS} seconds?"


def run_background(folder, meta):
    bad = unsafe_files(folder)
    if bad:
        raise ToolError(f"{bad[0]} has something I will not run, like sudo or rm -rf.")
    kind = meta["kind"]
    if kind == "static":
        open_web((Path(folder) / "index.html").as_uri())
        return f"Opened {Path(folder).name} in your browser."
    if kind in SERVER_KINDS:
        if needs_install(folder, meta):
            raise ToolError("It still needs its packages. Say build it again, or install them first.")
        port, proc = start_server(folder, meta)
        if not procs.wait_port(port, proc, SERVER_WAIT):
            last["error"] = procs.tail(Path(folder) / ".run.log")
            procs.stop(PROJECT)
            raise ToolError("The server did not start. Say fix the last error and I will try to repair it.")
        open_web(web_url(port))
        return f"{Path(folder).name} is running and open in your browser. Say stop it when you are done."
    log = Path(folder) / ".run.log"
    log.write_text("")
    procs.spawn(PROJECT, [py_for(folder), meta.get("entry") or "main.py"], folder, procs.clean_env(), log)
    time.sleep(1.5)
    if not procs.alive(PROJECT):
        last["error"] = procs.tail(log)
        raise ToolError("It closed right away. Say fix the last error and I will look at it.")
    return f"{Path(folder).name} is running. Say stop it when you are done."


@tool("run_project", 'args {"file": "<file or project name, or empty for the last build>"} - run a project: scripts run for up to 20 seconds, web and desktop apps start in the background and web apps open in the browser; for "run it"',
      risk="confirm", describe=_describe_run)
def run_project(args):
    folder = project_of(args)
    if folder and load_meta(folder)["kind"] != "script":
        return run_background(folder, load_meta(folder))
    path = run_target(args)
    exe = [sys.executable] if path.suffix == ".py" else [shutil.which("node") or "node"]
    try:
        r = subprocess.run(exe + [str(path)], cwd=path.parent, capture_output=True, text=True,
                           timeout=RUN_SECONDS, stdin=subprocess.DEVNULL, env=procs.clean_env())
    except subprocess.TimeoutExpired:
        return f"It was still running after {RUN_SECONDS} seconds, so I stopped it."
    except OSError:
        raise ToolError("I could not start that.")
    out = (r.stdout or "").strip().splitlines()
    err = (r.stderr or "").strip().splitlines()
    events.emit("sys", "\n".join(out[-15:] + err[-15:]))
    if r.returncode:
        last["error"] = "\n".join(err[-40:])
        return "It failed: " + (err[-1][:160] if err else f"exit code {r.returncode}") + ". Say fix the last error to repair it."
    return "It ran fine." + (f" Output: {out[-1][:160]}" if out else " It printed nothing.")


@tool("stop_project", 'args {} - stop the app that "run it" started; for "stop it", "stop the server"')
def stop_project(args):
    return "Stopped it." if procs.stop(PROJECT) else "Nothing of mine is running."


@tool("fix_last_error", 'args {} - read the last error from the project that was just built or run, fix the code and test again, up to 4 times; for "fix the last error"')
def fix_last_error(args):
    folder = project_of({})
    if folder is None:
        raise ToolError("I have no project to fix. Build something first.")
    meta = load_meta(folder)
    error = last["error"] or procs.tail(folder / ".run.log")
    if not error.strip():
        raise ToolError("I have no recent error to fix. Run the project first.")
    procs.stop(PROJECT)
    log = [f"fixing {folder.name}: " + (error.strip().splitlines() or [""])[-1][:160]]
    fixes = 0
    rel = fix_once(folder, meta, error, meta.get("request", ""), backup=True)
    if rel:
        fixes = 1
        log.append(f"fix 1: rewrote {rel}")
    ok, more, out = check_and_fix(folder, meta, meta.get("request", ""), log, backup=True) if rel else (False, 0, error)
    return report(folder, ok, fixes + more, out, log)


@tool("add_feature", 'args {"feature": "<what to add>", "project": "<project name, or empty for the last build>"} - add a feature to a project in the workspace, then test it; for "add dark mode to my todo app"')
def add_feature(args):
    feature = str(args.get("feature") or "").strip()
    if not feature:
        raise ToolError("What should I add?")
    folder = find_project(args.get("project"))
    if folder is None or not inside(folder):
        raise ToolError("I could not find that project in the code workspace.")
    meta = load_meta(folder) or {"kind": "script", "entry": "main.py"}
    request = meta.get("request") or folder.name
    listing = "\n".join(f"- {p.relative_to(folder)}" for p in source_files(folder)[:20])
    plan = brain.code(f"Project: {request}\nFiles:\n{listing}\nFeature to add: {feature}", 200, system=FEATURE_PLAN)
    targets = []
    for line in str(plan).splitlines():
        m = re.match(r"^\W*([\w./-]+\.\w{1,5})\s*:\s*(.*)$", line.strip())
        if m and m.group(1).count("/") <= 1 and ".." not in m.group(1) and not m.group(1).startswith((".", "/")):
            targets.append((m.group(1), m.group(2)))
    targets = targets[:3] or [(meta.get("entry") or ENTRY.get(meta.get("kind"), "main.py"), feature)]
    changed = []
    for i, (rel, what) in enumerate(targets):
        if i:
            time.sleep(GAP)
        path = folder / rel
        old = path.read_text(errors="ignore") if path.exists() else ""
        if len(old) > MAX_CHARS:
            continue
        prompt = (f"Project: {request}\nFeature to add: {feature}\n"
                  + (f"Current {rel}:\n{old}\n\nReturn the complete updated {rel}." if old else f"Write the new file {rel}: {what}"))
        text = brain.code(prompt, FILE_TOKENS, system=EDIT_SYSTEM + " " + KIND_NOTES.get(meta.get("kind"), ""))
        if not text:
            continue
        body = _fence(text)
        if UNSAFE.search(body):
            raise ToolError(f"The change to {rel} had something I will not write, like sudo or rm -rf, so I stopped.")
        if body.strip() != old.strip():
            write_project_file(folder, rel, body, backup=True)
            changed.append(rel)
    if not changed:
        raise ToolError("I could not make that change right now. Try again in a minute.")
    meta.setdefault("kind", "script")
    save_meta(folder, meta)
    last.update(dir=folder, main=folder / (meta.get("entry") or ENTRY.get(meta["kind"], "main.py")))
    return complete(folder, meta, f"{request}. Now also: {feature}", None, backup=True)


@tool("explain_file", 'args {"file": "<file name, or empty for the last project file>"} - explain what a code file does in a few sentences; for "explain this file", "explain main.py"')
def explain_file(args):
    path = locate(args.get("file"), ("explain_file", {}))
    text = path.read_text(errors="ignore")
    if not text.strip():
        raise ToolError(f"{path.name} is empty.")
    reply = brain.code(f"File {path.name}:\n{text[:6000]}\n\nExplain in three short spoken sentences what this file does and how it is organised. "
                       "No code, no lists.", 300)
    if not reply:
        raise ToolError("I could not read it back right now. Try again in a minute.")
    return " ".join(reply.split())


@tool("git_init_project", 'args {"project": "<project name, or empty for the last build>"} - run git init in a project in the workspace, local only, with a .gitignore; for "git init this project"')
def git_init_project(args):
    folder = find_project(args.get("project"))
    if folder is None or not inside(folder):
        raise ToolError("I could not find that project in the code workspace.")
    if not shutil.which("git"):
        raise ToolError("Git is not installed.")
    if (folder / ".git").exists():
        return f"{folder.name} is already a git repository."
    r = subprocess.run(["git", "init", "-q", "-b", "main"], cwd=folder, capture_output=True, text=True, timeout=30, env=procs.clean_env())
    if r.returncode:
        raise ToolError("Git could not start a repository there.")
    ignore = folder / ".gitignore"
    if not ignore.exists():
        ignore.write_text(".venv/\n__pycache__/\n*.pyc\n*.bak\n.run.log\n.jarvis.json\n")
    return f"Started a local git repository in {folder.name}. Nothing is committed and there is no remote."
