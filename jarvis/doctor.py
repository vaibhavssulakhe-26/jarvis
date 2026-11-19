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


def check_listening():
    """The measured background level, the active mode and the speech detector."""
    from .actions import events
    from .core import state
    from .voice import listen, ptt, vad
    floor = events.mic.get("floor") or state.get("noise_floor")
    backend = events.mic.get("vad") or vad.Detector().backend
    key = ptt.key_name()
    detail = (f"{listen.mode_label()} mode, background {floor:.3f}" if floor else f"{listen.mode_label()} mode, background not measured yet")
    detail += f", detector {backend}, push to talk " + (key[4:] if key else "off")
    if floor > 0.05:
        return item("listening", WARN, detail, "The background is loud: lower the input volume, or try crowd mode or push to talk")
    return item("listening", PASS, detail)


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
    from .brain import local
    url = local.url()
    try:
        r = requests.get(url + "/api/tags", timeout=3, proxies={"http": None, "https": None})
        models = r.json().get("models", [])
        names = [m.get("name", "") for m in models]
    except (requests.RequestException, ValueError):
        return item("ollama", WARN, "not running", "Start it with: ollama serve (Jarvis also starts it when needed)")
    from .brain import brain
    chat = [n for n in names if n and not any(x in n.lower() for x in brain.EMBED_WORDS)]
    wanted = config.get("OLLAMA_MODEL")
    if not chat:
        return item("ollama", WARN, "running, no chat model installed", f"ollama pull {wanted or brain.OLLAMA_DEFAULT}")
    if wanted and wanted not in chat and wanted + ":latest" not in chat:
        return item("ollama", WARN, f"running, OLLAMA_MODEL {wanted} is not installed", f"ollama pull {wanted}")
    brain.note_models(models)
    chosen = brain.pick_ollama_model(names)
    size = next((int(m.get("size") or 0) for m in models if m.get("name") == chosen), 0) / 2**30
    try:
        held = next((int(m.get("size") or 0) for m in requests.get(url + "/api/ps", timeout=3, proxies={"http": None, "https": None}).json().get("models", []) if m.get("name") == chosen), 0) / 2**30
    except (requests.RequestException, ValueError):
        held = 0.0
    free = brain._free_gb()
    detail = f"running, {chosen}" + (f", {free:.1f} GB free" if free is not None else "") + (f", needs about {size * 1.25:.1f} GB" if size else "")
    fit = brain.fits(free, size, held)
    if fit is False:
        return item("ollama", WARN, detail + ", does not fit right now", "Close heavy apps, or set OLLAMA_MODEL to a smaller model")
    return item("ollama", PASS, detail + (", fits" if fit else ""))


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


def check_telegram():
    from . import telegram
    state = telegram.status()
    if state == "off":
        return item("telegram", PASS, "off")
    if not telegram.token():
        return item("telegram", WARN, "on, token not set", "Add TELEGRAM_BOT_TOKEN to .env (from @BotFather)")
    if state == "not paired":
        return item("telegram", WARN, "not paired", "Start Jarvis, then send the pairing code to your bot")
    return item("telegram", PASS, "paired")


def check_wiki():
    from .research import wiki
    why, detail = wiki.state()
    if why == "off":
        return item("offline wiki", PASS, "pack not set (optional)", "Set OFFLINE_WIKI to a ZIM file, see the README")
    if why == "ready":
        return item("offline wiki", PASS, f"pack found: {detail}")
    if why == "no libzim":
        return item("offline wiki", WARN, "pack found, python-libzim is not installed", "pip install libzim")
    return item("offline wiki", WARN, f"pack not found: {detail}", "Check the OFFLINE_WIKI path in .env")


def check_holo():
    from . import holo
    why = holo.problem()
    return item("holo", WARN if why else PASS, "not set up" if why else "ready", why)


def check_brain_mode():
    mode = config.brain_mode()
    return item("brain mode", PASS, mode, "")


def check_advanced():
    from .brain import advanced
    if config.offline():
        return item("advanced (cloud)", PASS, "off in offline mode")
    if not (config.get("GROQ_API_KEY") or config.get("OPENROUTER_API_KEY")):
        return item("advanced (cloud)", WARN, "needs setup: no cloud key", "Add GROQ_API_KEY to .env; until then everything runs on the local model")
    return item("advanced (cloud)", PASS, f"{advanced.used()} of {advanced.daily()} calls used today")


def run(level=None, skip_mic=False):
    """The full list of results. `level` replaces the microphone level reader (used by the checks)."""
    results = []
    for make in (
        lambda: item("microphone", WARN, "skipped") if skip_mic else check_mic(level or live_level),
        check_wake,
        check_listening,
        lambda: key_status("Groq key", "GROQ_API_KEY"),
        lambda: key_status("OpenRouter key", "OPENROUTER_API_KEY"),
        lambda: key_status("Gmail login", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"),
        check_brain_mode,
        check_advanced,
        check_telegram,
        check_wiki,
        check_holo,
        check_ollama,
        lambda: check_tool("mpv", "sudo dnf install mpv"),
        lambda: check_tool("tesseract", "sudo dnf install tesseract"),
        lambda: check_tool("openscad", "sudo dnf install openscad"),
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


def ollama_report(text="can you hear me?"):
    """`python -m jarvis.doctor --ollama`: where Ollama is, what the settings say, and the exact call a chat turn makes. Returns (lines, ok)."""
    import os
    from .brain import brain, local
    out = []
    out.append(f"url          {local.url()}  (from {'OLLAMA_URL' if config.get('OLLAMA_URL') else 'OLLAMA_HOST' if (os.environ.get('OLLAMA_HOST') or config.get('OLLAMA_HOST')) else 'the default'})")
    proxies = local.proxy_variables()
    out.append("proxy        " + (", ".join(proxies) + " are set; Ollama calls ignore them" if proxies else "no proxy variables set; Ollama calls never use one"))
    names = []
    for label, base in (("localhost", "http://localhost:11434"), ("127.0.0.1", "http://127.0.0.1:11434")):
        try:
            r = local.http.get(base + "/api/tags", timeout=3)
            names = names or [m.get("name", "") for m in r.json().get("models", [])]
            out.append(f"{label:<12} HTTP {r.status_code}")
        except requests.RequestException as e:
            out.append(f"{label:<12} {type(e).__name__}: {str(e)[:90]}")
    wanted = config.get("OLLAMA_MODEL")
    chosen = brain._ollama_model()
    installed = chosen in names or chosen + ":latest" in names
    out.append(f"model        .env OLLAMA_MODEL={wanted or '(not set)'}, chosen {chosen}, " + ("installed" if installed else "NOT in ollama list: ollama pull " + chosen))
    out.append("installed    " + (", ".join(names) or "(none, or Ollama is not answering)"))
    free = brain._free_gb()
    loaded = brain._loaded()
    out.append(f"memory       {free:.1f} GB free, gate {brain.MIN_FREE_GB} GB, " + ("loaded now: " + ", ".join(loaded) if loaded else "no model loaded (the first call is cold)") if free is not None else "memory       unknown")
    out.append(f"timeouts     first word {local.FIRST_COLD} s cold, {local.FIRST_WARM} s warm; {local.GAP_SECONDS} s between chunks after that")
    messages, _, limit = brain.chat_request(text)
    sent = local.compact(messages)
    out.append(f"request      '{text}', about {brain.estimate(sent)} tokens (the chat prompt was {brain.estimate(messages)}), up to {local.predict_cap(limit, False)} tokens back")
    started = time.time()
    reply, code = brain._try_ollama(messages, limit, False)
    took = time.time() - started
    if reply:
        info = local.LAST
        out.append(f"result       pass, {took:.1f} s, first word after {info.get('first_token', 0):.1f} s ({'warm' if info.get('warm') else 'cold'}): {' '.join(reply.split())[:160]}")
        return out, True
    info = local.LAST
    out.append(f"result       FAIL after {took:.1f} s: {info.get('message', 'no answer')}")
    out.append(f"detail       kind={info.get('kind')} exception={info.get('exc') or '-'} status={info.get('status') or '-'} url={info.get('url')} model={info.get('model')}")
    return out, False


if __name__ == "__main__":
    if "--ollama" in sys.argv:
        lines, good = ollama_report()
        print("\n".join(lines))
        sys.exit(0 if good else 1)
    started = time.time()
    out = run()
    print(report(out))
    print(f"\n{summary(out)} ({time.time() - started:.1f}s)")
    sys.exit(1 if any(r["status"] == FAIL for r in out) else 0)
