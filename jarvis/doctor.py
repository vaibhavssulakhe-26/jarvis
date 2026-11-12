"""Diagnostics: `python -m jarvis.doctor`, or say "run diagnostics". One line per item: pass, warn or fail, with a one-line fix.
Keys are only ever reported as set or not set."""
import shutil
import sys
import time
from pathlib import Path

import requests

from .core import config

PASS, WARN, FAIL = "pass", "warn", "fail"
MIN_FREE_GB = 1.5
WARN_FREE_GB = 2.5


def item(name, status, detail, fix=""):
    return {"name": name, "status": status, "detail": detail, "fix": fix}


def check_mic(level=None):
    """The default input device and, when a level is available, whether it is moving. `level` is a function returning 0 to 1 or None."""
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="input")
    except Exception:
        return item("microphone", FAIL, "no input device found", "Plug in or enable a microphone and check the system sound settings")
    name = str(dev.get("name", "input"))[:40]
    value = level() if level else None
    if value is None:
        return item("microphone", PASS, f"{name} (level not measured)")
    if value < 0.0005:
        return item("microphone", WARN, f"{name}, silent (level {value:.4f})", "Unmute the mic and raise MIC_GAIN in .env")
    return item("microphone", PASS, f"{name}, level {value:.3f}")


def live_level():
    """The loudness Ears last reported, or a very short test recording when the app is not running."""
    from .actions import events
    if events.level:
        return float(events.level)
    try:
        import numpy as np
        import sounddevice as sd
        audio = sd.rec(int(0.4 * 16000), samplerate=16000, channels=1, dtype="float32")
        sd.wait()
        return float(np.std(audio))
    except Exception:
        return None


def check_wake():
    files = config.wake_files()
    try:
        import openwakeword  # noqa: F401
    except ImportError:
        return item("wake word", FAIL, "openwakeword is not installed", "pip install --no-deps openwakeword")
    if not files:
        return item("wake word", FAIL, "no wake model in models/", "Put an .onnx wake model in models/ (see README)")
    shared = [n for n in ("embedding_model", "melspectrogram") if not (config.MODELS / f"{n}.onnx").exists()]
    if shared:
        return item("wake word", WARN, f"{config.wake_label()}, missing {', '.join(shared)}", "Run: python -c 'import openwakeword; openwakeword.utils.download_models()'")
    return item("wake word", PASS, f"model files for {config.wake_label()} found")


def key_status(label, *names):
    have = all(config.get(n) for n in names)
    return item(label, PASS if have else WARN, "set" if have else "not set",
                "" if have else f"Add {' and '.join(names)} to .env" + (" (optional)" if label != "Groq key" else ""))


def check_ollama():
    url = config.get("OLLAMA_URL", "http://localhost:11434")
    try:
        r = requests.get(url + "/api/tags", timeout=3)
        names = [m.get("name", "") for m in r.json().get("models", [])]
    except (requests.RequestException, ValueError):
        return item("ollama", WARN, "not running", "Start it with: ollama serve (Jarvis also starts it when needed)")
    from .brain import brain
    chat = [n for n in names if n and not any(x in n.lower() for x in brain.EMBED_WORDS)]
    wanted = config.get("OLLAMA_MODEL")
    if not chat:
        return item("ollama", WARN, "running, no chat model installed", f"ollama pull {wanted or brain.OLLAMA_DEFAULT}")
    if wanted and wanted not in chat and wanted + ":latest" not in chat:
        return item("ollama", WARN, f"running, OLLAMA_MODEL {wanted} is not installed", f"ollama pull {wanted}")
    chosen = brain.pick_ollama_model(names)
    return item("ollama", PASS, f"running, using {chosen}")


def check_tool(name, fix):
    path = shutil.which(name)
    return item(name, PASS if path else WARN, "found" if path else "not found", "" if path else fix)


def check_browser():
    from .actions import browser
    if not browser.playwright_ok():
        return item("browser control", WARN, "playwright is not installed", "pip install playwright")
    if not browser.ready():
        return item("browser control", WARN, "no browser for Playwright", "Install Google Chrome or run: playwright install chromium")
    return item("browser control", PASS, "playwright and a browser are available")


def check_voice():
    from .voice import voices
    path = voices.current_path()
    if path is None:
        return item("piper voice", FAIL, "no voice file", "python scripts/get_voices.py")
    return item("piper voice", PASS, f"{voices.current_name()} ({Path(path).name})")


def check_ram():
    try:
        import psutil
        free = psutil.virtual_memory().available / 2 ** 30
    except ImportError:
        return item("free memory", WARN, "psutil is not installed", "pip install psutil")
    if free < MIN_FREE_GB:
        return item("free memory", FAIL, f"{free:.1f} GB free", "Close heavy apps; the offline model needs about 1.5 GB")
    if free < WARN_FREE_GB:
        return item("free memory", WARN, f"{free:.1f} GB free", "Close a few apps before using the offline model")
    return item("free memory", PASS, f"{free:.1f} GB free")


def check_venv():
    expected = (config.ROOT / ".venv").resolve()
    active = Path(sys.prefix).resolve()
    if active == expected:
        return item("virtual environment", PASS, ".venv is active")
    return item("virtual environment", WARN, f"running from {active}", "Run: source .venv/bin/activate")


def check_brain_mode():
    mode = config.brain_mode()
    return item("brain mode", PASS, mode, "")


def run(level=None, skip_mic=False):
    """The full list of results. `level` replaces the microphone level reader (used by the checks)."""
    results = []
    for make in (
        lambda: item("microphone", WARN, "skipped") if skip_mic else check_mic(level or live_level),
        check_wake,
        lambda: key_status("Groq key", "GROQ_API_KEY"),
        lambda: key_status("OpenRouter key", "OPENROUTER_API_KEY"),
        lambda: key_status("Gmail login", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
        check_brain_mode,
        check_ollama,
        lambda: check_tool("mpv", "sudo dnf install mpv"),
        lambda: check_tool("tesseract", "sudo dnf install tesseract"),
        check_browser,
        check_voice,
        check_ram,
        check_venv,
    ):
        try:
            results.append(make())
        except Exception as e:
            results.append(item("check", WARN, f"could not run ({type(e).__name__})"))
    return results


def format_line(r):
    mark = {PASS: "pass", WARN: "warn", FAIL: "FAIL"}[r["status"]]
    return f"{mark}  {r['name']:<20} {r['detail']}" + (f"  -> {r['fix']}" if r["fix"] and r["status"] != PASS else "")


def report(results):
    return "\n".join(format_line(r) for r in results)


def summary(results):
    """One or two spoken sentences."""
    bad = [r for r in results if r["status"] == FAIL]
    warn = [r for r in results if r["status"] == WARN]
    ok = sum(1 for r in results if r["status"] == PASS)
    line = f"{ok} of {len(results)} checks passed."
    if bad:
        line += " Failing: " + ", ".join(r["name"] for r in bad[:3]) + "."
    elif warn:
        line += " Worth a look: " + ", ".join(r["name"] for r in warn[:3]) + "."
    else:
        line += " Everything looks healthy."
    return line


if __name__ == "__main__":
    started = time.time()
    out = run()
    print(report(out))
    print(f"\n{summary(out)} ({time.time() - started:.1f}s)")
    sys.exit(1 if any(r["status"] == FAIL for r in out) else 0)
