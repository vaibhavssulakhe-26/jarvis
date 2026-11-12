"""The platform layer with both backends mocked, the profile folders, the setup wizard helpers, and a scan that no Linux-only command is
called outside jarvis/platform/linux.py. No hardware, no network. Run: python scripts/platform_check.py"""
import contextlib
import io
import os
import re
import stat
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-platform-"))
os.environ["JARVIS_DATA"] = str(tmp / "data")
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp / "state")
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from jarvis import platform, setup  # noqa: E402
from jarvis.actions import tools  # noqa: E402
from jarvis.platform import linux, mac  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


class Recorder:
    """Stands in for subprocess.run / Popen and remembers every command."""

    def __init__(self, stdout=""):
        self.calls, self.stdout = [], stdout

    def run(self, cmd, **kw):
        self.calls.append((list(cmd), kw.get("input")))
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout.encode() if kw.get("capture_output") and not kw.get("text") else self.stdout, stderr="")

    def popen(self, cmd, **kw):
        self.calls.append((list(cmd), None))
        return mock.Mock()

    def commands(self):
        return [c[0][0] for c in self.calls]


def with_backend(module, rec, home=None):
    stack = contextlib.ExitStack()
    stack.enter_context(mock.patch.object(module.subprocess, "run", rec.run))
    stack.enter_context(mock.patch.object(module.subprocess, "Popen", rec.popen))
    stack.enter_context(mock.patch.object(module.shutil, "which", lambda n: "/usr/bin/" + n))
    if home:
        stack.enter_context(mock.patch.object(module.Path, "home", classmethod(lambda cls: home)))
    platform.use(module)
    return stack


# ---- the interface ----
check("every call in the interface exists on the Linux backend", [n for n in platform.API if not hasattr(linux, n)] == [], [n for n in platform.API if not hasattr(linux, n)])
missing_mac = sorted(n for n in platform.API if not hasattr(mac, n))
print("     not on the Mac backend yet:", ", ".join(missing_mac))
check("the Mac backend is missing only what is documented", set(missing_mac) <= {"brightness_change", "brightness_set", "inhibit_notifications"}, missing_mac)
fake = types.ModuleType("fake")
fake.NAME = "fake"
fake.clipboard_read = lambda: "from the fake"
platform.use(fake)
check("use() swaps the backend", platform.name() == "fake" and platform.clipboard_read() == "from the fake")
try:
    platform.volume_get()
    check("a missing function raises Unsupported", False)
except platform.Unsupported as e:
    check("a missing function raises Unsupported, speakable", "not supported on this system" in str(e) and isinstance(e, tools.ToolError), str(e))

# ---- linux ----
rec = Recorder()
with with_backend(linux, rec):
    platform.clipboard_write("hello")
    platform.open_target("https://example.org")
    platform.notify("Jarvis", "hi")
    platform.notify("Reminder", "stand up", urgent=True)
    platform.power("suspend")
    platform.lock_screen()
    platform.volume_set(40)
    platform.volume_change(-10)
    platform.unmute()
    platform.media_control("pause")
cmds = [c[0] for c in rec.calls]
check("linux clipboard uses wl-copy", (["wl-copy"], b"hello") in rec.calls)
check("linux opens with xdg-open", ["xdg-open", "https://example.org"] in cmds)
check("linux notifies with notify-send, critical when urgent", ["notify-send", "Jarvis", "hi"] in cmds and ["notify-send", "-u", "critical", "Reminder", "stand up"] in cmds)
check("linux power and lock go through systemctl and loginctl", ["systemctl", "suspend"] in cmds and ["loginctl", "lock-session"] in cmds)
check("linux volume goes through wpctl", ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "0.40"] in cmds
      and ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"] in cmds and ["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"] in cmds)
check("linux media keys go through playerctl", ["playerctl", "pause"] in cmds)
with with_backend(linux, Recorder(stdout="Volume: 0.35")):
    check("linux reads the volume", platform.volume_get() == 35)
with mock.patch.object(linux.shutil, "which", lambda n: None):
    platform.use(linux)
    check("linux without a clipboard tool says so", platform.clipboard_write("x") is False)
    try:
        platform.brightness_set(40)
        check("linux without brightnessctl is a spoken error", False)
    except tools.ToolError as e:
        check("linux without brightnessctl is a spoken error", "brightnessctl" in str(e))
home = tmp / "home"
home.mkdir()
rec = Recorder()
with with_backend(linux, rec, home):
    status = platform.install_schedule("jarvis-routines", ["/x/python", "-m", "jarvis.routines", "run"], 15, "Jarvis routines", "/x")
    platform.install_autostart("jarvis", ["/x/python", "-m", "jarvis.main"])
timer = (home / ".config/systemd/user/jarvis-routines.timer").read_text()
check("linux writes a systemd user timer that catches up after sleep", "OnUnitActiveSec=15min" in timer and "Persistent=true" in timer)
check("and enables it", ["systemctl", "--user", "enable", "--now", "jarvis-routines.timer"] in [c[0] for c in rec.calls] and "enabled" in status)
check("linux autostart is an XDG desktop entry", "Exec=/x/python -m jarvis.main" in (home / ".config/autostart/jarvis.desktop").read_text())
check("linux folders follow XDG", linux.runtime_dir() == tmp / "jarvis" and linux.state_dir() == tmp / "state" / "jarvis" and linux.data_dir(root) == root / "data")

# ---- mac ----
rec = Recorder(stdout="42")
with with_backend(mac, rec, home):
    platform.clipboard_write("hello")
    platform.open_target("https://example.org")
    platform.notify("Jarvis", 'say "hi"')
    platform.power("suspend")
    platform.lock_screen()
    platform.volume_set(40)
    got = platform.volume_get()
    platform.capture_screen.__call__  # exists
    try:
        platform.capture_screen(tmp / "never-made.png")
    except tools.ToolError:
        pass
    status = platform.install_schedule("jarvis-routines", ["/x/python", "-m", "jarvis.routines", "run"], 15, "Jarvis routines", "/x")
    platform.install_autostart("jarvis", ["/x/python", "-m", "jarvis.main"])
    names = platform.name()
cmds = [c[0] for c in rec.calls]
check("mac clipboard uses pbcopy", (["pbcopy"], b"hello") in rec.calls)
check("mac opens with open", ["open", "https://example.org"] in cmds)
check("mac notifications use AppleScript with quotes escaped", any(c[0] == "osascript" and 'display notification "say \\"hi\\""' in " ".join(c) for c in cmds))
check("mac power and lock use pmset", ["pmset", "sleepnow"] in cmds and ["pmset", "displaysleepnow"] in cmds)
check("mac volume uses AppleScript", any(c[0] == "osascript" and "set volume output volume 40" in " ".join(c) for c in cmds) and got == 42)
check("mac screenshots use screencapture", ["screencapture", "-x", str(tmp / "never-made.png")] in cmds)
agent = home / "Library/LaunchAgents/com.jarvis.jarvis-routines.plist"
import plistlib  # noqa: E402
plist = plistlib.loads(agent.read_bytes())
check("mac scheduling is a launchd plist with an interval", plist["StartInterval"] == 900 and plist["ProgramArguments"][-1] == "run" and ["launchctl", "load", str(agent)] in cmds, plist)
check("mac autostart is a launchd login item", plistlib.loads((home / "Library/LaunchAgents/com.jarvis.jarvis.plist").read_bytes())["RunAtLoad"] is True)
check("mac folders are under Application Support", "Application Support/Jarvis" in str(mac.state_dir()) and str(mac.data_dir(root)).endswith("Jarvis/data"))
platform.use(mac)
for call in (lambda: platform.brightness_set(50), lambda: platform.inhibit_notifications(True)):
    try:
        call()
        check("an unsupported Mac feature raises Unsupported", False)
    except platform.Unsupported as e:
        check("an unsupported Mac feature says so plainly", str(e).endswith("is not supported on this system."), str(e))
with mock.patch.object(mac.subprocess, "run", Recorder().run):
    try:
        tools.TOOLS["brightness"]["fn"]({"text": "brightness up"})
        check("the brightness tool is a spoken error on a Mac", False)
    except tools.ToolError as e:
        check("the brightness tool is a spoken error on a Mac", "not supported on this system" in str(e), str(e))
platform.use(linux)

# ---- no Linux-only command outside linux.py ----
FORBIDDEN = re.compile(r"wl-copy|wl-paste|kdotool|systemctl|xdg-open|notify-send|loginctl|spectacle|wpctl|playerctl|brightnessctl|import evdev|from evdev|"
                       r"QtDBus|osascript|pbcopy|pbpaste|screencapture|launchctl|pmset")
ALLOWED = {"platform/linux.py", "platform/mac.py", "setup.py"}  # setup.py only lists tool names to look for
offenders = []
for path in sorted((root / "jarvis").rglob("*.py")):
    rel = str(path.relative_to(root / "jarvis"))
    if rel in ALLOWED:
        continue
    for n, line in enumerate(path.read_text().splitlines(), 1):
        if FORBIDDEN.search(line):
            offenders.append(f"{rel}:{n}: {line.strip()[:70]}")
check("no wl-copy, kdotool, systemd or other platform command outside the backends", not offenders, "\n" + "\n".join(offenders))
check("setup.py only names tools to check for", not re.search(r"subprocess\.\w+\(\[?\"(wl-copy|kdotool|systemctl)", (root / "jarvis/setup.py").read_text()))

# ---- profiles ----
def paths(profile):
    env = {**os.environ, "JARVIS_PROFILE": profile}
    env.pop("JARVIS_DATA", None)
    env.pop("USER_NAME", None)
    out = subprocess.run([sys.executable, "-c", "from jarvis.core import config, state; print(config.DATA); print(config.RUNTIME); print(state.PATH); print(config.get('USER_NAME'))"],
                         cwd=root, env=env, capture_output=True, text=True)
    return out.stdout.split("\n")


try:
    (root / ".env.platformcheckzz").write_text("USER_NAME=Zed\n")
    default, zed = paths(""), paths("platformcheckzz")
    other = paths("other")
finally:
    (root / ".env.platformcheckzz").unlink(missing_ok=True)
check("the default profile keeps data/ as it was", default[0] == str(root / "data"))
check("a profile has its own data, runtime and state folders", zed[0] == str(root / "data/profiles/platformcheckzz") and zed[1].endswith("jarvis/platformcheckzz")
      and zed[2].endswith("jarvis/platformcheckzz/state.json") and zed[0] != other[0] and zed[2] != other[2], zed)
check("the profile's own .env.<name> sets USER_NAME", zed[3] == "Zed", zed)
check("another profile does not see it", other[3] != "Zed")
bad_name = paths("../evil")
check("an unsafe profile name is ignored", bad_name[0] == str(root / "data"), bad_name)

# ---- setup wizard ----
info = setup.detect()
check("the wizard detects the system and Python", info["os"] in ("linux", "mac") and info["python_ok"])
report = setup.tool_report({"os": "mac", "manager": "brew"}, which=lambda t: None if t == "mpv" else "/bin/" + t)
check("the tool report names what is missing and how to install it", ("mpv", False, "music and video", "brew install mpv") in report, report)
check("apt and dnf hints", setup.install_hint("wl-copy", "dnf") == "sudo dnf install wl-clipboard" and setup.install_hint("mpv", "apt-get") == "sudo apt-get install mpv")
env = tmp / "env-test"
env.write_text("# comment\nUSER_NAME=\nGROQ_API_KEY=\n# OPENROUTER_API_KEY=\nOTHER=keep\n")
asked = []
out = io.StringIO()
with contextlib.redirect_stdout(out):
    status = setup.ask_keys(env, ask=lambda p: asked.append(p) or "me@example.test", secret=lambda p: asked.append(p) or "gsk_SECRET_TYPED_VALUE_123")
text = env.read_text()
check("keys are written to the file", "GROQ_API_KEY=gsk_SECRET_TYPED_VALUE_123" in text and "GMAIL_ADDRESS=me@example.test" in text and "OTHER=keep" in text and "# comment" in text)
check("the status says set, never the value", status["GROQ_API_KEY"] == "set" and "gsk_SECRET" not in out.getvalue() and "gsk_SECRET" not in str(status))
check("secrets are asked for with hidden input, the address is not", len(asked) == 4)
check(".env is readable by its owner only", stat.S_IMODE(env.stat().st_mode) == 0o600, oct(env.stat().st_mode))
with contextlib.redirect_stdout(io.StringIO()):
    again = setup.ask_keys(env, ask=lambda p: 1 / 0, secret=lambda p: 1 / 0)
check("keys that exist are not asked for again", again["GROQ_API_KEY"] == "set")
try:
    setup.write_env({"A": "x\nB=y"}, env)
    check("a line break in a value is refused", False)
except ValueError:
    check("a line break in a value is refused", True)

files = {}


class FakeResp:
    def __init__(self, data):
        self.data = io.BytesIO(data)

    def __enter__(self):
        return self.data

    def __exit__(self, *a):
        return False


def fake_fetch(url, timeout=0):
    files[url] = True
    if url.endswith(".json") and "broken" in url:
        raise setup.urllib.error.URLError("no network")
    return FakeResp(b"data")


failed = setup.download_voice("en_US-ryan-medium", tmp / "voices", fetch=fake_fetch)
check("the voice URL follows the Piper layout", "en/en_US/ryan/medium/en_US-ryan-medium.onnx" in " ".join(files) and not failed, files)
check("both voice files are saved", (tmp / "voices/en_US-ryan-medium.onnx").exists() and (tmp / "voices/en_US-ryan-medium.onnx.json").exists())
check("a failed download is listed with its URL", setup.download_voice("en_GB-broken-low", tmp / "v2", fetch=fake_fetch)[0].endswith("en_GB-broken-low.onnx.json"))
try:
    setup.download_voice("../../etc/passwd", tmp / "v3", fetch=fake_fetch)
    check("a bad voice name is refused", False)
except ValueError:
    check("a bad voice name is refused", True)
calls = []
fake_backend = types.SimpleNamespace(install_schedule=lambda *a: calls.append(("schedule", a[0], a[2])) or "timer on",
                                     install_autostart=lambda *a: calls.append(("autostart", a[0])) or "login item on")
check("the wizard installs nothing without a yes", setup.offer_services(Path("/x/python"), ask=lambda p: "n", backend=fake_backend) == [] and calls == [])
lines = setup.offer_services(Path("/x/python"), ask=lambda p: "y", backend=fake_backend)
check("a yes installs the schedule and the login item through the platform layer", calls == [("schedule", "jarvis-routines", 15), ("autostart", "jarvis")] and len(lines) == 2, calls)
calls.clear()
setup.offer_services(Path("/x/python"), ask=lambda p: 1 / 0, backend=fake_backend, assume=("schedule",))
check("--schedule installs only the schedule, without asking", calls == [("schedule", "jarvis-routines", 15)])
venv_calls = []
setup.create_venv(tmp / "proj", run=lambda cmd, **k: venv_calls.append(cmd) or None)
check("the venv step creates .venv, installs requirements and openwakeword without deps",
      venv_calls[0][1:3] == ["-m", "venv"] and any("requirements.txt" in c for c in venv_calls[2]) and "--no-deps" in venv_calls[3], venv_calls)
check("install.sh parses", subprocess.run(["bash", "-n", str(root / "scripts/install.sh")]).returncode == 0)
sys.exit(1 if bad else 0)
