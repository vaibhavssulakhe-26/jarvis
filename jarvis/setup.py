"""First-run setup: `python -m jarvis.setup`. Checks the system, creates .venv and installs the requirements, downloads a Piper voice, asks for
API keys with hidden input and writes them to .env (never printing them), and ends with `python -m jarvis.doctor`.
Only the standard library is used, so it runs before anything is installed. Options: --yes (no questions, keep what exists),
--no-venv, --schedule, --autostart, --voice NAME, --profile NAME."""
import getpass
import os
import re
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
EXAMPLE = ROOT / ".env.example"
MIN_PYTHON = (3, 10)
VOICE_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"
VOICES = ("en_US-ryan-medium", "en_US-joe-medium", "en_GB-alan-medium", "en_US-amy-medium", "en_US-lessac-medium", "en_GB-jenny_dioco-medium")
KEYS = (("GROQ_API_KEY", True, "Groq key (the main brain; free at console.groq.com)"),
        ("OPENROUTER_API_KEY", True, "OpenRouter key (first backup, optional)"),
        ("GMAIL_ADDRESS", False, "Gmail address for the briefing and drafts (optional)"),
        ("GMAIL_APP_PASSWORD", True, "Gmail app password, not your normal password (optional)"))
TOOLS = {  # tool: (needed on, why)
    "linux": (("mpv", "music and video"), ("tesseract", "reading the screen"), ("wl-copy", "the clipboard (package wl-clipboard)"),
              ("playerctl", "media keys"), ("git", "the coding helper"), ("spectacle", "screenshots (or grim)")),
    "mac": (("mpv", "music and video"), ("tesseract", "reading the screen"), ("ollama", "the offline brain"), ("git", "the coding helper")),
}


def say(text=""):
    print(text, flush=True)


def detect():
    """{'os': 'linux' | 'mac' | other, 'python_ok', 'python', 'manager'} for this machine."""
    name = "mac" if sys.platform == "darwin" else "linux" if sys.platform.startswith("linux") else sys.platform
    manager = next((m for m in (("brew",) if name == "mac" else ("dnf", "apt-get", "pacman", "zypper")) if shutil.which(m)), "")
    return {"os": name, "python": ".".join(str(n) for n in sys.version_info[:3]), "python_ok": sys.version_info[:2] >= MIN_PYTHON, "manager": manager}


def install_hint(tool, manager):
    package = {"wl-copy": "wl-clipboard", "spectacle": "spectacle"}.get(tool, tool)
    return {"brew": f"brew install {package}", "dnf": f"sudo dnf install {package}", "apt-get": f"sudo apt-get install {package}",
            "pacman": f"sudo pacman -S {package}", "zypper": f"sudo zypper install {package}"}.get(manager, f"install {package}")


def tool_report(info, which=shutil.which):
    """[(tool, found, why, hint)] for the tools this system wants."""
    return [(t, which(t) is not None, why, install_hint(t, info["manager"])) for t, why in TOOLS.get(info["os"], ())]


def venv_python(root=ROOT):
    return root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"


def create_venv(root=ROOT, run=subprocess.run):
    """Create .venv if it is missing and install the requirements. Returns the venv's python."""
    py = venv_python(root)
    if not py.exists():
        run([sys.executable, "-m", "venv", str(root / ".venv")], check=True)
    run([str(py), "-m", "pip", "install", "--upgrade", "pip"], check=True)
    run([str(py), "-m", "pip", "install", "-r", str(root / "requirements.txt")], check=True)
    run([str(py), "-m", "pip", "install", "--no-deps", "openwakeword==0.3.0"], check=True)
    return py


def voice_url(name, ext):
    lang, locale = name.split("-")[0].split("_")[0], name.split("-")[0]
    speaker, quality = name.split("-")[1], name.split("-")[2]
    return f"{VOICE_BASE}{lang}/{locale}/{speaker}/{quality}/{name}{ext}"


def download_voice(name, dest, fetch=urllib.request.urlopen):
    """Download both files of a Piper voice into dest. Returns the list of files that could not be fetched (with their URLs)."""
    if not re.fullmatch(r"[a-z]{2}_[A-Z]{2}-[A-Za-z0-9_]+-(?:x_low|low|medium|high)", name):
        raise ValueError(f"{name!r} does not look like a Piper voice name, for example en_US-ryan-medium")
    dest.mkdir(parents=True, exist_ok=True)
    failed = []
    for ext in (".onnx", ".onnx.json"):
        target = dest / (name + ext)
        if target.exists() and target.stat().st_size > 0:
            continue
        url = voice_url(name, ext)
        part = target.with_name(target.name + ".part")
        try:
            with fetch(url, timeout=60) as r, open(part, "wb") as f:
                shutil.copyfileobj(r, f)
            part.replace(target)
        except (urllib.error.URLError, OSError):
            part.unlink(missing_ok=True)
            failed.append(url)
    return failed


def read_env(path=ENV):
    try:
        return path.read_text().splitlines()
    except FileNotFoundError:
        return EXAMPLE.read_text().splitlines() if EXAMPLE.exists() and path == ENV else []


def write_env(values, path=ENV):
    """Set KEY=value lines in the file, keeping every other line. The file is readable by its owner only."""
    lines = read_env(path)
    for key, value in values.items():
        if re.search(r"[\r\n]", value):
            raise ValueError("a value cannot contain a line break")
        new = f"{key}={value}"
        for i, line in enumerate(lines):
            if re.match(rf"\s*#?\s*{re.escape(key)}\s*=", line) and not line.lstrip().startswith("# "):
                lines[i] = new
                break
        else:
            lines.append(new)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def has_value(key, path=ENV):
    return any(re.match(rf"\s*{re.escape(key)}\s*=\s*\S", line) for line in read_env(path)) if path.exists() else False


def ask_keys(path, ask=input, secret=getpass.getpass, assume_yes=False):
    """Prompt for each key (hidden for secrets) and write the answers. Returns {key: 'set' or 'not set'} and never the values."""
    got = {}
    for key, hidden, label in KEYS:
        if has_value(key, path) or assume_yes:
            continue
        value = (secret if hidden else ask)(f"{label}\n  {key} (Enter to skip): ").strip()
        if value:
            got[key] = value
    if got:
        write_env(got, path)
    return {key: "set" if has_value(key, path) else "not set" for key, _, _ in KEYS}


def offer_services(python, ask=input, backend=None, assume=()):
    """Offer the scheduled routines and start-at-login. `assume` can hold 'schedule' and 'autostart' to do them without asking.
    Returns the status lines. Nothing is installed without a yes or the matching option."""
    if backend is None:
        from jarvis import platform as backend
    lines = []
    if "schedule" in assume or (not assume and ask("\nRun the routines (morning briefing, inbox triage, notes reindex) on a schedule? [y/N] ").strip().lower() == "y"):
        lines.append(backend.install_schedule("jarvis-routines", [str(python), "-u", "-m", "jarvis.routines", "run"], 15, "Jarvis routines", ROOT))
    if "autostart" in assume or (not assume and ask("Start Jarvis when you log in? [y/N] ").strip().lower() == "y"):
        lines.append(backend.install_autostart("jarvis", [str(python), "-m", "jarvis.main"]))
    return lines


def run_doctor(python):
    return subprocess.run([str(python), "-m", "jarvis.doctor"], cwd=ROOT).returncode


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    yes = "--yes" in argv
    option = lambda name: argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else ""  # noqa: E731
    info = detect()
    say(f"System: {info['os']}, Python {info['python']}" + (f", package manager {info['manager']}" if info["manager"] else ""))
    if not info["python_ok"]:
        say(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} or newer is needed. Install it and run this again.")
        return 1
    if info["os"] not in TOOLS:
        say(f"{info['os']} is not a supported system; the steps below may not all work.")
    say("\nTools:")
    for tool, found, why, hint in tool_report(info):
        say(f"  {'ok     ' if found else 'missing'} {tool}: {why}" + ("" if found else f"   ->  {hint}"))
    python = Path(sys.executable)
    if "--no-venv" not in argv:
        say("\nCreating .venv and installing requirements (this takes a few minutes) ...")
        try:
            python = create_venv()
        except subprocess.CalledProcessError as e:
            say(f"Installing failed (step: {' '.join(str(c) for c in e.cmd[:5])}). Fix that and run the setup again; it continues where it stopped.")
            return 1
    voice = option("--voice") or (VOICES[0] if yes else (input(f"\nPiper voice [{VOICES[0]}] (others: {', '.join(VOICES[1:3])} ...): ").strip() or VOICES[0]))
    say(f"Downloading the voice {voice} ...")
    try:
        failed = download_voice(voice, ROOT / "models" / "voices")
    except ValueError as e:
        say(str(e))
        failed = []
    if failed:
        say("Could not download these; put the files in models/voices by hand:\n  " + "\n  ".join(failed))
    profile = option("--profile")
    target = ROOT / f".env.{profile}" if profile else ENV
    if not target.exists() and not profile and EXAMPLE.exists():
        shutil.copyfile(EXAMPLE, target)
        os.chmod(target, stat.S_IRUSR | stat.S_IWUSR)
    if not yes:
        name = input("\nYour name (used in greetings, Enter to skip): ").strip()
        if name:
            write_env({"USER_NAME": name, "USER_NICKNAME": name}, target)
    say("\nKeys are typed hidden and saved in " + target.name + "; they are never shown.")
    for key, status in ask_keys(target, assume_yes=yes).items():
        say(f"  {key}: {status}")
    assume = tuple(o for o in ("schedule", "autostart") if "--" + o in argv)
    if not yes or assume:
        try:
            for line in offer_services(python, assume=assume):
                say("  " + line)
        except Exception as e:
            say(f"  could not set up the schedule: {e}")
    say("\nRunning the doctor ...\n")
    return run_doctor(python)


if __name__ == "__main__":
    sys.exit(main())
