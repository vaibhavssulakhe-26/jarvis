"""`python -m jarvis.bench` runs the 30 eval phrases and prints average and p95 latency, tokens per request and the provider mix.
The default uses a mocked brain, so it measures routing and prompt size for free. `--live` sends the brain requests to the real
providers, which spends tokens but shows real latency and which provider answered. The result goes to data/eval/bench-<date>.json."""
import sys
from collections import Counter
from datetime import datetime

from . import evalkit
from .core import config, jsonfile


def percentile(values, pct):
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, max(0, round(pct / 100 * (len(ordered) - 1) + 0.4999)))]


def run(live=False, cases=None, probe=None):
    """Run the phrases and return the summary dict. `probe(text, setup, live)` replaces evalkit.run_one (used by the checks)."""
    probe = probe or evalkit.run_one
    rows = []
    for category, text, want, setup in cases or evalkit.CASES:
        got, tokens, ms, kind, provider = probe(text, setup, live)
        rows.append({"category": category, "phrase": text, "got": got, "pass": evalkit.judge(want, got, tokens), "tokens": tokens,
                     "ms": round(ms, 1), "provider": provider})
    times = [r["ms"] for r in rows]
    brain_rows = [r for r in rows if r["tokens"]]
    return {"date": datetime.now().strftime("%Y-%m-%d"), "time": datetime.now().strftime("%H:%M:%S"), "mode": "live" if live else "mock",
            "total": len(rows), "passed": sum(r["pass"] for r in rows),
            "avg_ms": round(sum(times) / len(times), 1) if times else 0.0, "p95_ms": round(percentile(times, 95), 1),
            "brain_requests": len(brain_rows),
            "avg_tokens": round(sum(r["tokens"] for r in brain_rows) / len(brain_rows)) if brain_rows else 0,
            "providers": dict(Counter(r["provider"] for r in rows)), "results": rows}


def save(summary):
    path = config.DATA / "eval" / f"bench-{summary['date']}.json"
    jsonfile.write(path, summary, indent=1)
    return path


def latest():
    files = sorted((config.DATA / "eval").glob("bench-*.json"))
    return jsonfile.read(files[-1]) if files else None


def describe(s):
    mix = ", ".join(f"{k} {v}" for k, v in sorted(s["providers"].items()))
    return (f"Benchmark {s['date']} ({s['mode']}): {s['passed']} of {s['total']} routed as expected. "
            f"Latency average {s['avg_ms']} ms, p95 {s['p95_ms']} ms. {s['brain_requests']} brain requests, "
            f"{s['avg_tokens']} tokens each. Providers: {mix}.")


def main(argv):
    live = "--live" in argv
    summary = run(live)
    for r in summary["results"]:
        print(("pass " if r["pass"] else "FAIL ") + f"{r['phrase']!r:48} {r['got']:26} {r['tokens']:5} tok {r['ms']:8.1f} ms  {r['provider']}")
    print("\n" + describe(summary))
    print("saved", save(summary))
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
