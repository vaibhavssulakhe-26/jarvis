"""Design a 3D model with OpenSCAD: the brain writes the .scad, the openscad CLI builds the .stl, trimesh checks it against the printer bed.
Everything lands in models/<name>/ (latest copy at the top, every version in v1, v2 ...). Jarvis designs and opens the slicer for you;
it never talks to a printer."""
import re
import resource
import shlex
import shutil
import subprocess
import time
from pathlib import Path

import numpy as np

from ..brain import brain
from ..core import config
from ..core.errors import Ask
from . import events, procs
from .tools import ToolError, tool

MODELS = config.ROOT / "models"
READY = MODELS / "ready"
DEFAULT_BED = (220.0, 220.0, 250.0)
DEFAULT_SLICER = "flatpak run com.prusa3d.PrusaSlicer"
COMPILE_SECONDS = 60
MEMORY_LIMIT = 3 * 2 ** 30
SCAD_TOKENS = 1200
MAX_SCAD = 20000
SETTLE = 1.0
THIN_WALL = 1.2
TINY_PART = 2.0
last = {"slug": "", "at": 0.0}
_ask = {"request": "", "until": 0.0}

SYSTEM = ("You write OpenSCAD for 3D printing. Reply with one fenced code block and nothing else. Units are millimetres. Declarative code only: "
          "primitives, transforms, boolean operations, modules and variables. No import, no include or use, no surface, no file access. "
          "One solid part that sits flat on z = 0 so it can print without supports where possible. Walls at least 1.5 mm thick. "
          "Put the main dimensions as variables at the top. Use $fn of 64 at most.")
FIT_WORDS = re.compile(r"\b(iphone|phone|laptop|tablet|ipad|screws?|bolts?|nuts?|washers?|m[2-9]|m1\d|pens?|pencils?|cups?|mugs?|bottles?|usb|hdmi|cables?|"
                       r"raspberry pi|arduino|keyboard|camera|headphones?|battery|batteries|rail|pipe|tube)\b", re.I)
NUMBERS = re.compile(r"\d|\b(?:one|two|three|four|five|six|seven|eight|nine|ten|twenty|thirty|forty|fifty|hundred)\b", re.I)
SHELL = re.compile(r"\b(?:system|exec|popen|shell|eval|subprocess)\s*\(|`|\$\(|\b(?:bash|curl|wget|chmod)\b|\bsh\s+-c|\bos\.", re.I)
READS = re.compile(r"\b(import|surface)\s*\(([^)]*)\)|\b(include|use)\s*<([^>]*)>")
COMMENTS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)


# ---------- where things live ----------
def _slug(text):
    return re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")[:30] or "model"


def _name_from(request):
    words = re.findall(r"[a-z0-9]+", request.lower())
    skip = {"make", "design", "model", "create", "build", "print", "me", "a", "an", "the", "of", "for", "3d", "please", "i", "want", "need", "to", "my", "some"}
    return "-".join([w for w in words if w not in skip][:4])


def versions(slug):
    folder = MODELS / slug
    return sorted(int(p.name[1:]) for p in folder.glob("v[0-9]*") if p.is_dir() and (p / "model.stl").is_file()) if folder.is_dir() else []


def models():
    if not MODELS.is_dir():
        return []
    found = [d for d in MODELS.iterdir() if d.is_dir() and d.name != "ready" and (d / "model.scad").is_file()]
    return sorted(found, key=lambda d: (d / "model.scad").stat().st_mtime, reverse=True)


def current(name=""):
    """The model folder the user means: a spoken name, the one just made, or the newest."""
    want = _slug(name) if name else ""
    if want:
        for d in models():
            if want in d.name or d.name in want:
                return d
        raise ToolError(f"I do not have a model called {str(name)[:30]}.")
    if last["slug"] and (MODELS / last["slug"] / "model.scad").is_file():
        return MODELS / last["slug"]
    found = models()
    if not found:
        raise ToolError("There is no model yet. Describe one, like make a 3D model of a phone stand.")
    return found[0]


def have_model():
    return bool(models())


def recent():
    """True when a model was made or changed in the last hour, so "this is good" or "add a hole" is about it."""
    found = models()
    newest = max(last["at"], (found[0] / "model.scad").stat().st_mtime if found else 0.0)
    return time.time() - newest < 3600


# ---------- rules for the code the brain writes ----------
def unsafe(code):
    """A reason to refuse this .scad, or an empty string."""
    if len(code) > MAX_SCAD:
        return "the file is far too long"
    body = COMMENTS.sub("", code)
    if SHELL.search(body):
        return "it has a shell call"
    for m in READS.finditer(body):
        raw = m.group(2) or m.group(4) or ""
        path = (re.search(r"\"([^\"]*)\"", raw) or re.search(r"([^\s,=]+)\s*$", raw))
        path = path.group(1) if path else raw.strip()
        target = (MODELS / path).resolve() if path and not path.startswith(("/", "~")) else None
        if target is None or ".." in Path(path).parts or not target.is_file() or MODELS.resolve() not in target.parents:
            return f"it reads {path[:40] or 'a file'}, which is not inside models"
    if not re.search(r"\b(cube|sphere|cylinder|polyhedron|linear_extrude|rotate_extrude|polygon|circle|square)\s*\(", body):
        return "it does not draw anything"
    return ""


def _fence(text):
    m = re.search(r"```[\w+-]*\n(.*?)```", text, re.S)
    return (m.group(1) if m else text).strip("\n") + "\n"


# ---------- building ----------
def _limits():
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_LIMIT, MEMORY_LIMIT))


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env=procs.clean_env(OPENSCADPATH=str(MODELS)), preexec_fn=_limits)


def first_error(log):
    """The first useful OpenSCAD line, not the whole log."""
    lines = [l.strip() for l in str(log).splitlines() if l.strip()]
    for pat in (r"^ERROR:", r"^Parser error", r"error", r"^WARNING:.*(?:unknown|undefined|not found)"):
        for l in lines:
            if re.search(pat, l, re.I):
                return l[:160]
    return (lines[-1] if lines else "no message from OpenSCAD")[:160]


def compile_scad(scad, stl):
    """(True, "") or (False, the first useful error line)."""
    try:
        r = _run(["openscad", "-o", str(stl), str(scad)], COMPILE_SECONDS)
    except FileNotFoundError:
        raise ToolError("OpenSCAD is not installed. Run: sudo dnf install openscad.")
    except subprocess.TimeoutExpired:
        raise ToolError(f"OpenSCAD took more than {COMPILE_SECONDS} seconds, so I stopped it. The shape may be too detailed.")
    if r.returncode != 0 or not Path(stl).is_file() or Path(stl).stat().st_size < 84:
        Path(stl).unlink(missing_ok=True)
        return False, first_error((r.stderr or "") + "\n" + (r.stdout or ""))
    return True, ""


def write_code(prompt):
    text = brain.code(prompt, SCAD_TOKENS, system=SYSTEM)
    if not text:
        raise ToolError("I could not write that right now. Try again in a minute.")
    code = _fence(text)
    why = unsafe(code)
    if why:
        raise ToolError(f"The code the brain wrote was refused: {why}. Nothing was built.")
    return code


def build(slug, code, prompt, number):
    """Compile into models/<slug>/v<number>, fixing a compile error once. Returns the version folder."""
    ver = MODELS / slug / f"v{number}"
    ver.mkdir(parents=True, exist_ok=True)
    scad, stl = ver / "model.scad", ver / "model.stl"
    try:
        for attempt in (1, 2):
            scad.write_text(code, encoding="utf-8")
            ok, err = compile_scad(scad, stl)
            if ok:
                return ver
            if attempt == 2:
                raise ToolError(f"The model would not compile: {err}")
            code = write_code(f"{prompt}\n\nThis code failed to compile with: {err}\nThe code was:\n```\n{code}```\nReturn the corrected whole file.")
    except BaseException:
        if not stl.is_file():
            shutil.rmtree(ver, ignore_errors=True)
        raise


# ---------- checks ----------
def bed():
    raw = config.get("BED_SIZE") or ""
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", raw)]
    return tuple(nums[:3]) if len(nums) >= 3 else DEFAULT_BED


def _mm(v):
    return f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"


def wall_estimate(mesh, samples=60):
    """About how thick the walls are: shoot rays inward from sample points and take the low end of the distances. None when it is too big to check."""
    if len(mesh.faces) > 40000:
        return None
    tri = mesh.triangles
    e1, e2 = tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]
    idx = np.random.default_rng(0).choice(len(tri), min(samples, len(tri)), replace=False)
    found = []
    for i in idx:
        d = -mesh.face_normals[i]
        o = mesh.triangles_center[i] + d * 1e-3
        h = np.cross(d, e2)
        a = np.einsum("ij,ij->i", e1, h)
        with np.errstate(all="ignore"):
            f = 1.0 / a
            s = o - tri[:, 0]
            u = f * np.einsum("ij,ij->i", s, h)
            q = np.cross(s, e1)
            v = f * (q @ d)
            t = f * np.einsum("ij,ij->i", e2, q)
            hit = (np.abs(a) > 1e-9) & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-3)
        if hit.any():
            found.append(t[hit].min())
    return float(np.percentile(found, 10)) if found else None


def inspect(stl):
    """(size in mm, [(ok, line)]) for a built model: size, bed, watertight, wall, loose parts, overhangs."""
    import trimesh
    mesh = trimesh.load(str(stl), force="mesh")
    if len(mesh.faces) == 0:
        raise ToolError("The model came out empty. Try describing it again.")
    size = [float(x) for x in mesh.extents]
    lines = [(True, f"Size {_mm(size[0])} by {_mm(size[1])} by {_mm(size[2])} mm.")]
    b = bed()
    label = f"{_mm(b[0])} by {_mm(b[1])} by {_mm(b[2])} mm bed"
    if all(s <= lim + 0.01 for s, lim in zip(size, b)):
        lines.append((True, f"Fits the {label}."))
    elif all(s <= lim + 0.01 for s, lim in zip(sorted(size), sorted(b))):
        lines.append((False, f"Too big as drawn for the {label}, but it fits if turned."))
    else:
        lines.append((False, f"Too big for the {label}."))
    lines.append((True, "Watertight.") if mesh.is_watertight else (False, "Not watertight, the slicer may need to repair it."))
    wall = wall_estimate(mesh)
    if wall is not None:
        lines.append((wall >= THIN_WALL, f"Thinnest wall is about {wall:.1f} mm." + ("" if wall >= THIN_WALL else " That is thin.")))
    parts = mesh.split(only_watertight=False, repair=False)
    if len(parts) > 1:
        tiny = sum(1 for p in parts if max(p.extents) < TINY_PART)
        lines.append((False, f"{len(parts)} separate pieces" + (f", {tiny} tiny (under {TINY_PART:.0f} mm)." if tiny else ".")))
    else:
        lines.append((True, "One solid piece."))
    area = mesh.area_faces
    low = mesh.triangles_center[:, 2] > mesh.bounds[0][2] + 0.1
    over = float(area[(mesh.face_normals[:, 2] < -0.7071) & low].sum())
    share = over / float(area.sum()) if area.sum() else 0.0
    if share > 0.05 and over > 100:
        lines.append((False, f"About {share * 100:.0f} percent of the surface overhangs more than 45 degrees, so it needs supports."))
    else:
        lines.append((True, "No big overhangs."))
    return size, lines


# ---------- tools ----------
def _describe(folder, number, request, size, lines):
    text = f"# {folder.name}\n\nRequest: {request}\nVersion: {number}\nSize: {_mm(size[0])} x {_mm(size[1])} x {_mm(size[2])} mm\n\n## Checks\n"
    return text + "".join(f"- {'ok' if ok else 'warning'}: {line}\n" for ok, line in lines)


def _publish(slug, ver, number, request):
    size, lines = inspect(ver / "model.stl")
    (ver / "description.md").write_text(_describe(MODELS / slug, number, request, size, lines), encoding="utf-8")
    for f in ("model.scad", "model.stl", "description.md"):
        shutil.copyfile(ver / f, MODELS / slug / f)
    last.update(slug=slug, at=time.time())
    report = "\n".join(("" if ok else "! ") + line for ok, line in lines)
    print(f"  [model {slug} v{number}]\n" + report)
    events.emit("sys", f"{slug} v{number}\n{report}")
    warns = [line for ok, line in lines if not ok]
    spoken = f"Built {slug.replace('-', ' ')}, version {number}: {_mm(size[0])} by {_mm(size[1])} by {_mm(size[2])} millimeters."
    if warns:
        spoken += " " + " ".join(warns[:2]) + (" The rest is in description.md." if len(warns) > 2 else "")
    else:
        spoken += " It fits the bed and the checks are clean."
    return spoken + _show(slug)


def _show(slug):
    """With HOLO_AUTO on, show the model on the hologram; otherwise only say how. Quiet when handctl is not set up."""
    from .. import holo
    if not holo.ready():
        return ""
    if not config.flag("HOLO_AUTO"):
        return " Say show it to view it on the hologram."
    try:
        holo.show(slug)
    except ToolError as e:
        return f" I could not show it: {e}"
    return " It is on the hologram."


def asking():
    return time.time() < _ask["until"]


def take_answer(text):
    """After the measurement question, the next sentence is the numbers."""
    if not asking():
        return None
    _ask["until"] = 0.0
    t = " ".join(str(text).split()).strip(" .")
    if not t or re.match(r"^(?:no|never mind|cancel|stop|forget it)\b", t, re.I) or not NUMBERS.search(t):
        return None
    return {"request": f"{_ask['request']}. Real measurements in mm: {t}", "measured": True}


@tool("make_model", 'args {"request": "<the object, with any real measurements in mm>"} - design a 3D model: the brain writes OpenSCAD, it is built to an STL, checked against the printer bed and shown on the hologram; design only, never prints; for "make a 3D model of ...", "design a ..."')
def make_model(args):
    request = " ".join(str(args.get("request") or "").split())[:400]
    if not request:
        raise ToolError("Tell me what to make, for example a phone stand for an iPhone, 75 millimeters wide.")
    fit = FIT_WORDS.search(request)
    if fit and not NUMBERS.search(request) and not args.get("measured"):
        _ask.update(request=request, until=time.time() + 60)
        raise Ask(f"What are the real measurements of the {fit.group(1).lower()} in millimeters? I will not guess them.")
    slug = _slug(_name_from(request))
    n = 2
    while (MODELS / slug).exists():
        slug = f"{_slug(_name_from(request))}-{n}"
        n += 1
    prompt = f"Design this for 3D printing: {request}"
    code = write_code(prompt)
    ver = build(slug, code, prompt, 1)
    return _publish(slug, ver, 1, request)


@tool("revise_model", 'args {"change": "<what to change>", "name": "<model name, empty for the latest>"} - edit the latest 3D model and build the next version, keeping the old ones; for "make it 5 mm taller", "add a hole"')
def revise_model(args):
    change = " ".join(str(args.get("change") or "").split())[:300]
    if not change:
        raise ToolError("Tell me what to change, for example make it 5 millimeters taller.")
    folder = current(args.get("name") or "")
    have = versions(folder.name) or [0]
    src = folder / "model.scad"
    old = (folder / f"v{have[-1]}" / "model.scad") if have[-1] else src
    prompt = f"Here is the current OpenSCAD file:\n```\n{old.read_text(encoding='utf-8')}```\nChange it like this: {change}\nReturn the whole updated file."
    code = write_code(prompt)
    number = have[-1] + 1
    ver = build(folder.name, code, prompt, number)
    return _publish(folder.name, ver, number, change)


def _launch_slicer(argv):
    return subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


@tool("prepare_print", 'args {"name": "<model name, empty for the latest>"} - the user approved the model ("this is good", "let\'s print it"): copy the STL to models/ready and open it in the slicer; never starts a print')
def prepare_print(args):
    folder = current(args.get("name") or "")
    have = versions(folder.name)
    stl = folder / f"v{have[-1]}" / "model.stl" if have else folder / "model.stl"
    if not stl.is_file():
        raise ToolError("That model has no STL file yet.")
    READY.mkdir(parents=True, exist_ok=True)
    target = READY / f"{folder.name}-v{have[-1] if have else 1}.stl"
    shutil.copyfile(stl, target)
    argv = shlex.split(config.get("SLICER_CMD") or DEFAULT_SLICER) + [str(target)]
    if not shutil.which(argv[0]):
        raise ToolError(f"I copied it to models/ready as {target.name}, but I could not find the slicer program {argv[0]}. Set SLICER_CMD in the .env file.")
    proc = _launch_slicer(argv)
    time.sleep(SETTLE)
    if proc.poll() not in (None, 0):
        raise ToolError(f"I copied it to models/ready as {target.name}, but the slicer did not start.")
    return "Opened in the slicer. Printing is yours to start."
