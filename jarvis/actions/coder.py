"""Small coding helper: build a project one file per call, edit a file, find bugs, run the result.
Everything is written inside the workspace folder; changes to existing files wait for a spoken yes."""
import difflib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ..brain import brain
from ..core import config
from . import events
from .tools import ToolError, _launch, tool

WORKSPACE = Path(config.get("CODE_WORKSPACE") or "~/Projects/jarvis-builds").expanduser()
MAX_FILES = 4
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
last = {"dir": None, "main": None}
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


@tool("build_project", 'args {"request": "<what to build, in words>"} - build a small project or web page: plan the files, write them in the code workspace and open them in the editor; for "build me a ...", "create a ...", "write a ..."')
def build_project(args):
    request = str(args.get("request") or "").strip()
    if not request:
        raise ToolError("What should I build?")
    plan = brain.code(f"Project: {request}", 300, system=PLAN_SYSTEM.format(n=MAX_FILES))
    name, files = parse_plan(plan, request)
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
        text = brain.code(prompt, FILE_TOKENS, system=FILE_SYSTEM)
        if not text:
            if not written:
                raise ToolError("I could not write that right now. Try again in a minute.")
            break
        body = _fence(text)
        if len(body) > MAX_CHARS:
            body = body[:MAX_CHARS]
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body)
        written.append(rel)
    main = folder / main_file([(w, "") for w in written])
    last.update(dir=folder, main=main)
    events.emit("sys", f"Built {folder}: " + ", ".join(written))
    opened = open_in_editor(main)
    line = f"Built {len(written)} file{'s' if len(written) > 1 else ''} in {folder.name}."
    return line + (f" Opened in {opened}." if opened else "")


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


def _describe_run(args):
    path = run_target(args)
    return f"Run {path.name} from {path.parent.name} for up to {RUN_SECONDS} seconds?"


@tool("run_project", 'args {"file": "<file name, or empty for the last build>"} - run the project\'s main Python or JavaScript file with a 20 second limit; for "run it"',
      risk="confirm", describe=_describe_run)
def run_project(args):
    path = run_target(args)
    exe = [sys.executable] if path.suffix == ".py" else [shutil.which("node") or "node"]
    try:
        r = subprocess.run(exe + [str(path)], cwd=path.parent, capture_output=True, text=True,
                           timeout=RUN_SECONDS, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"It was still running after {RUN_SECONDS} seconds, so I stopped it."
    except OSError:
        raise ToolError("I could not start that.")
    out = (r.stdout or "").strip().splitlines()
    err = (r.stderr or "").strip().splitlines()
    events.emit("sys", "\n".join(out[-15:] + err[-15:]))
    if r.returncode:
        return "It failed: " + (err[-1][:160] if err else f"exit code {r.returncode}") + ". Say find bugs to fix it."
    return "It ran fine." + (f" Output: {out[-1][:160]}" if out else " It printed nothing.")
