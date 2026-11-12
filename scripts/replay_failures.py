"""Runs the failed or corrected requests from data/traces.jsonl through today's router (mock brain, no tools run) and prints what changed.
Run: python scripts/replay_failures.py [--file path/to/traces.jsonl] [--limit 10]"""
import json
import os
import sys
import tempfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
args = sys.argv[1:]
source = Path(args[args.index("--file") + 1]) if "--file" in args else Path(os.environ.get("JARVIS_DATA") or root / "data") / "traces.jsonl"
limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 10
scratch = tempfile.mkdtemp(prefix="jarvis-replay-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(root))

from jarvis import evalkit, traces  # noqa: E402


def new_tool(got):
    return got[6:] if got.startswith("local:") else "brain"


def compare(row):
    """(old route text, new route text, changed) for one trace row."""
    got, tokens, ms, kind, _ = evalkit.run_one(row.get("heard", ""), "")
    old = row.get("tool") or ("brain" if str(row.get("route", "")).startswith("brain") else "?")
    now = new_tool(got)
    return old, now, old != now


def main():
    try:
        rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    except OSError:
        print(f"no traces at {source}")
        return 0
    failed = traces.failures(limit, rows)
    if not failed:
        print("no failed or corrected requests")
        return 0
    changed = 0
    for row in failed:
        old, now, diff = compare(row)
        changed += diff
        why = "corrected" if row.get("corrected") else row.get("reason") or "failed"
        print(f"{'CHANGED' if diff else 'same   '}  {row.get('heard', '')[:48]!r:52} was {old} ({why}) -> now {now}")
    print(f"\n{len(failed)} replayed, {changed} route differently now")
    return 0


if __name__ == "__main__":
    sys.exit(main())
