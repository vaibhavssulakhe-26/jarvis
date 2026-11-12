"""Doctor: every item reports pass, warn or fail with a fix hint, keys are never printed, and the offline model follows free memory.
Fake data only. Run: python scripts/doctor_check.py"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-doctor-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["GROQ_API_KEY"] = "gsk_SECRET_VALUE_THAT_MUST_NOT_PRINT_123456"
os.environ["GMAIL_ADDRESS"] = "someone@example.test"
os.environ["GMAIL_APP_PASSWORD"] = "SECRET_APP_PASSWORD_VALUE"
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from jarvis import doctor  # noqa: E402
from jarvis.actions import diag_tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402

bad = []
os.environ.pop("OPENROUTER_API_KEY", None)
os.environ.pop("OLLAMA_MODEL", None)
os.environ.pop("BRAIN", None)


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


class FakeResponse:
    def __init__(self, names):
        self.names = names

    def json(self):
        return {"models": [{"name": n} for n in self.names]}


def by_name(results):
    return {r["name"]: r for r in results}


# a healthy fake machine
healthy = mock.patch.multiple(doctor, check_wake=lambda: doctor.item("wake word", "pass", "fake"), check_browser=lambda: doctor.item("browser control", "pass", "fake"),
                              check_voice=lambda: doctor.item("piper voice", "pass", "fake"))
with healthy, mock.patch.object(doctor.requests, "get", lambda *a, **k: FakeResponse(["llama3.2:1b"])), \
        mock.patch.object(doctor.shutil, "which", lambda n: "/usr/bin/" + n), mock.patch.object(brain, "_free_gb", lambda: 5.0), \
        mock.patch.object(doctor.sys, "prefix", str(root / ".venv")):
    results = doctor.run(level=lambda: 0.02)
names = by_name(results)
check("the mic, wake word, keys, ollama, mpv, tesseract, browser, voice, ram and venv are all reported",
      {"microphone", "wake word", "Groq key", "OpenRouter key", "Gmail login", "ollama", "mpv", "tesseract", "browser control", "piper voice",
       "free memory", "virtual environment"} <= set(names), set(names))
check("every item has a status, a detail and a fix field", all(r["status"] in ("pass", "warn", "fail") and "detail" in r and "fix" in r for r in results))
check("keys are reported as set or not set", names["Groq key"]["detail"] == "set" and names["OpenRouter key"]["detail"] == "not set"
      and names["Gmail login"]["detail"] == "set")
report = doctor.report(results)
check("no secret ever appears in the output", "SECRET" not in report and "gsk_" not in report and "someone@example.test" not in report, report)
check("a missing optional key has a fix hint", "OPENROUTER_API_KEY" in names["OpenRouter key"]["fix"])
check("the microphone level is shown", "level 0.020" in names["microphone"]["detail"], names["microphone"]["detail"])
check("a present model passes", names["ollama"]["status"] == "pass", names["ollama"])
check("the active .venv passes", names["virtual environment"]["status"] == "pass")

# failure paths
with healthy, mock.patch.object(doctor.requests, "get", side_effect=doctor.requests.ConnectionError()), \
        mock.patch.object(doctor.shutil, "which", lambda n: None), mock.patch.object(brain, "_free_gb", lambda: 0.8), \
        mock.patch("psutil.virtual_memory", lambda: mock.Mock(available=0.8 * 2 ** 30)), mock.patch.object(doctor.sys, "prefix", "/usr"):
    sick = by_name(doctor.run(level=lambda: 0.0))
check("ollama down is a warning with a fix", sick["ollama"]["status"] == "warn" and "ollama serve" in sick["ollama"]["fix"])
check("missing mpv and tesseract have install hints", "dnf install mpv" in sick["mpv"]["fix"] and "dnf install tesseract" in sick["tesseract"]["fix"])
check("a silent mic warns", sick["microphone"]["status"] == "warn" or sick["microphone"]["status"] == "fail", sick["microphone"])
check("low memory fails", sick["free memory"]["status"] == "fail")
check("a different venv is a warning", sick["virtual environment"]["status"] == "warn" and "activate" in sick["virtual environment"]["fix"])
with healthy, mock.patch.object(doctor.requests, "get", lambda *a, **k: FakeResponse(["nomic-embed-text:latest"])):
    miss = by_name(doctor.run(level=lambda: 0.02))["ollama"]
check("no chat model says how to pull one", miss["status"] == "warn" and "ollama pull llama3.2:1b" in miss["fix"], miss)
os.environ["OLLAMA_MODEL"] = "qwen2.5:14b"
with healthy, mock.patch.object(doctor.requests, "get", lambda *a, **k: FakeResponse(["llama3.2:1b"])):
    miss = by_name(doctor.run(level=lambda: 0.02))["ollama"]
check("an override that is not installed says how to pull it", miss["status"] == "warn" and "ollama pull qwen2.5:14b" in miss["fix"], miss)
os.environ.pop("OLLAMA_MODEL")
with mock.patch.object(doctor, "check_wake", side_effect=RuntimeError("boom")):
    survived = doctor.run(skip_mic=True)
check("one broken check does not stop the others", len(survived) >= 10)

spoken = doctor.summary(results)
check("the spoken summary is short", spoken.count(".") <= 3 and "checks passed" in spoken, spoken)
with healthy, mock.patch.object(doctor.requests, "get", lambda *a, **k: FakeResponse(["llama3.2:1b"])), mock.patch.object(doctor, "live_level", lambda: 0.02):
    said = diag_tools.run_diagnostics({})
check("'run diagnostics' returns a summary", "checks passed" in said, said)

# offline model by free memory
installed = ["llama3.2:1b", "llama3.2:3b", "qwen2.5:7b", "nomic-embed-text:latest"]
check("under 2 GB free: the 1B model", brain.pick_ollama_model(installed, 1.2) == "llama3.2:1b")
check("2 to 4 GB free: a 3B model", brain.pick_ollama_model(installed, 3.0) == "llama3.2:3b")
check("above 4 GB free: a larger one", brain.pick_ollama_model(installed, 6.0) == "qwen2.5:7b")
check("2 to 4 GB with no 3B installed falls back to the 1B", brain.pick_ollama_model(["llama3.2:1b", "qwen2.5:7b"], 3.0) == "llama3.2:1b")
check("embedding models are never chosen", brain.pick_ollama_model(["nomic-embed-text", "llama3.2:1b"], 8.0) == "llama3.2:1b")
check("only an embedding model installed falls back to the default", brain.pick_ollama_model(["nomic-embed-text:latest"], 8.0) == brain.OLLAMA_DEFAULT)
os.environ["OLLAMA_MODEL"] = "qwen2.5:7b"
check("OLLAMA_MODEL in .env overrides the choice", brain.pick_ollama_model(installed, 1.2) == "qwen2.5:7b")
os.environ["OLLAMA_MODEL"] = "not-installed:9b"
check("an override that is not installed is ignored", brain.pick_ollama_model(installed, 3.0) == "llama3.2:3b")
os.environ.pop("OLLAMA_MODEL")
brain._ollama_name.update(t=0.0, name=None)
with mock.patch.object(brain._http, "get", lambda *a, **k: FakeResponse(installed)), mock.patch.object(brain, "_free_gb", lambda: 3.0):
    check("the model in use is chosen at startup and reported", brain.ollama_model_in_use() == "llama3.2:3b")
    check("'which model' names it", "llama3.2:3b" in diag_tools.which_model({}))
os.environ["BRAIN"] = "offline"
check("'which model' says offline mode", "offline mode" in diag_tools.which_model({}))
os.environ.pop("BRAIN")

# the command line
out = subprocess.run([sys.executable, "-m", "jarvis.doctor"], cwd=root, capture_output=True, text=True, env={**os.environ})
check("python -m jarvis.doctor prints a line per item", out.stdout.count("\n") >= 12 and ("pass" in out.stdout), out.stdout[-300:] + out.stderr[-300:])
check("and prints no key", "gsk_SECRET" not in out.stdout and "SECRET_APP_PASSWORD" not in out.stdout)
sys.exit(1 if bad else 0)
