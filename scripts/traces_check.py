"""Traces: one line per request, corrections, rotation, the failures list and the replay, all with fake data. Run: python scripts/traces_check.py"""
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-traces-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["XDG_STATE_HOME"] = str(tmp)
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))

from jarvis import bench, traces  # noqa: E402
from jarvis.actions import diag_tools, events  # noqa: E402
from jarvis.core import main as core  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def rows():
    return [json.loads(line) for line in traces.path().read_text().splitlines()]


# one line per request with every field
traces.begin("what time is it")
events.emit("route", "direct time_date")
traces.note(tool="time_date")
traces.add_tokens(0)
line = traces.end()
r = rows()
check("one JSON line per request", len(r) == 1 and r[0]["heard"] == "what time is it")
need = {"time", "heard", "route", "tool", "provider", "tokens", "latency_ms", "ok", "corrected"}
check("it has time, heard text, route, tool, provider, tokens, latency, success and corrected", need <= set(r[0]), set(r[0]))
check("the route comes from the route event", r[0]["route"] == "direct time_date")

traces.begin("explain recursion in simple words")
events.emit("route", "brain chat")
events.emit("provider", "groq")
traces.add_tokens(240)
traces.end()
check("provider and tokens are recorded", rows()[-1]["provider"] == "groq" and rows()[-1]["tokens"] == 240)

traces.begin("open the pod bay doors")
traces.fail("I cannot do that one yet")
traces.end()
check("a failure is recorded as not ok", rows()[-1]["ok"] is False and rows()[-1]["reason"])

# corrections
traces.begin("play some lofi beats")
traces.end()
traces.begin("play some lofi beats")
traces.end()
check("repeating a request marks the first as corrected", [x["corrected"] for x in rows()[-2:]] == [True, False], rows()[-2:])
traces.begin("set volume to forty")
traces.end()
traces.begin("no I said fifty")
traces.end()
check("contradicting a request marks it corrected", rows()[-2]["corrected"] is True)
traces.begin("do you want to continue")
traces.end()
traces.begin("no", answering=True)
traces.end()
check("answering a question is not a correction", rows()[-2]["corrected"] is False)
traces.begin("next")
traces.end()
traces.begin("next")
traces.end()
check("a short command twice is not a correction", rows()[-2]["corrected"] is False)
traces.begin("what is the weather in pune")
traces.end()
_t = traces._last["at"]
traces._last["at"] = time.time() - 600
traces.begin("what is the weather in pune")
traces.end()
check("an old request is not corrected by a later repeat", rows()[-2]["corrected"] is False)

# failures list
fails = traces.failures(10)
check("failures lists failed and corrected requests, newest first", fails and fails[0]["heard"] != "what time is it"
      and all(not f["ok"] or f["corrected"] for f in fails), [f["heard"] for f in fails])
check("a healthy request is not listed", all(f["heard"] != "what time is it" for f in fails))
for i in range(15):
    traces.begin(f"unknown request number {i}")
    traces.fail("no brain")
    traces.end()
check("at most ten failures are listed", len(traces.failures(10)) == 10)
said = diag_tools.show_failures({})
check("'show my failures' says how many and the latest", "10" in said and "unknown request number 14" in said, said)
core_seen = []
with mock.patch.object(core, "run_tool", lambda a, args, s: core_seen.append(a)), mock.patch.object(core.events, "emit", lambda *a, **k: None):
    core.direct("show my failures")
    core.direct("run diagnostics")
check("both commands route locally", core_seen == ["show_failures", "run_diagnostics"], core_seen)

# the handler writes traces
os.environ["TRACES"] = "on"
with mock.patch.object(core, "_handle", lambda text, via_wake=True: events.emit("route", "direct x") or False):
    before = len(rows())
    core.handle("hello there my friend")
check("main.handle writes a trace per request", len(rows()) == before + 1 and rows()[-1]["heard"] == "hello there my friend")
with mock.patch.object(core, "_handle", lambda text, via_wake=True: (_ for _ in ()).throw(RuntimeError("x"))):
    try:
        core.handle("this one crashes")
    except RuntimeError:
        pass
check("a crash is recorded as a failure", rows()[-1]["heard"] == "this one crashes" and rows()[-1]["ok"] is False)
os.environ["TRACES"] = "off"
n = len(rows())
traces.begin("not written")
traces.end()
check("TRACES=off writes nothing", len(rows()) == n)
os.environ["TRACES"] = "on"

# rotation
big = traces.path()
with mock.patch.object(traces, "MAX_BYTES", 2000):
    for i in range(60):
        traces.begin(f"fill the file {i}")
        traces.end()
check("the file is rotated at the size limit", big.with_name(big.name + ".1").exists() and big.stat().st_size < 4000, big.stat().st_size)
check("the default limit is 5 MB", traces.MAX_BYTES == 5 * 1024 * 1024)
check("the file is git-ignored", subprocess.run(["git", "check-ignore", "-q", "data/traces.jsonl"], cwd=root).returncode == 0)

# replay
fake = tmp / "fake-traces.jsonl"
fake.write_text("\n".join(json.dumps(x) for x in [
    {"id": 1, "time": "2026-11-12T09:00:00", "heard": "what time is it", "route": "brain chat", "tool": "", "ok": False, "reason": "no brain", "corrected": False},
    {"id": 2, "time": "2026-11-12T09:01:00", "heard": "hello", "route": "direct x", "tool": "", "ok": True, "corrected": True},
    {"id": 3, "time": "2026-11-12T09:02:00", "heard": "fine request", "route": "direct y", "tool": "y", "ok": True, "corrected": False},
]) + "\n")
out = subprocess.run([sys.executable, "scripts/replay_failures.py", "--file", str(fake)], cwd=root, capture_output=True, text=True)
check("replay_failures runs", out.returncode == 0, out.stderr[-300:])
check("it replays only failures and corrections", "2 replayed" in out.stdout and "fine request" not in out.stdout, out.stdout)
check("it shows what changed", "CHANGED" in out.stdout and "what time is it" in out.stdout and "now time_date" in out.stdout, out.stdout)

# benchmark with fake timings
seq = iter([(("local:time_date"), 0, 5.0, "local", "local")] * 10 + [("chat", 300, 100.0, "chat", "groq")] * 10 + [("chat", 340, 200.0, "chat", "openrouter")] * 10)
cases = [("c", f"phrase {i}", "chat", "") for i in range(30)]
summary = bench.run(cases=cases, probe=lambda text, setup, live: next(seq))
check("bench: average and p95 latency", summary["avg_ms"] == round((10 * 5 + 10 * 100 + 10 * 200) / 30, 1) and summary["p95_ms"] == 200.0, summary)
check("bench: tokens per brain request", summary["avg_tokens"] == 320 and summary["brain_requests"] == 20)
check("bench: provider mix", summary["providers"] == {"local": 10, "groq": 10, "openrouter": 10}, summary["providers"])
path = bench.save(summary)
check("bench: saved as bench-<date>.json", path.name.startswith("bench-") and json.loads(path.read_text())["total"] == 30)
check("bench: latest() reads it back", bench.latest()["avg_ms"] == summary["avg_ms"])
check("bench: command line runs", subprocess.run([sys.executable, "-m", "jarvis.bench"], cwd=root, capture_output=True, text=True,
      env={**os.environ}).returncode == 0)
sys.exit(1 if bad else 0)
