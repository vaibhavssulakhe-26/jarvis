"""'Jarvis stats': the latest eval result and which brain answered how often."""

from datetime import datetime

from ..core import config, jsonfile
from . import events
from .tools import tool

PROVIDERS = (("groq", "Groq"), ("groq-strong", "Groq large"), ("openrouter", "OpenRouter"), ("ollama", "Local model"))
COUNTERS = ("advanced",)


def latest_eval():
    """The newest data/eval/<date>.json, or None."""
    files = sorted((config.DATA / "eval").glob("*.json"))
    if not files:
        return None
    return jsonfile.read(files[-1])


def core_rate():
    """{'passed', 'total', 'at'} from the last run of scripts/core_check.py, or None."""
    return jsonfile.read(config.DATA / "core-check.json", None, dict)


def usage(days=7):
    """({provider: {'calls', 'tokens'}} summed over the last days, today's {provider: row}). Today's row is empty when nothing was asked today."""
    data = jsonfile.read(config.DATA / "usage.json", None, dict)
    if data is None:
        return {}, {}
    keys = sorted(data)[-days:]
    total = {}
    for k in keys:
        for name, row in data[k].items():
            if name in COUNTERS:
                continue
            t = total.setdefault(name, {"calls": 0, "tokens": 0})
            t["calls"] += row.get("calls", 0)
            t["tokens"] += row.get("tokens", 0)
    return total, {n: r for n, r in data.get(datetime.now().strftime("%Y-%m-%d"), {}).items() if n not in COUNTERS}


def advanced_today():
    """(calls used today, daily cap, tokens sent today) for the cloud tier."""
    from ..brain import advanced
    row = advanced.today("advanced")
    return row["calls"], advanced.daily(), row["tokens"]


def build():
    """(spoken line, full text for the screen)."""
    ev = latest_eval()
    week, today = usage()
    lines, spoken = [], []
    if ev:
        rate = round(100 * ev["passed"] / ev["total"]) if ev["total"] else 0
        lines.append(f"Eval {ev['date']}: {ev['passed']} of {ev['total']} passed ({rate}%), average {ev['avg_tokens']} tokens per brain request, "
                     f"{ev['avg_ms']} ms per phrase.")
        spoken.append(f"My last test passed {ev['passed']} of {ev['total']} phrases, {rate} percent, "
                      f"averaging {ev['avg_tokens']} tokens per request.")
    else:
        lines.append("No eval yet. Run: python scripts/eval_phrases.py")
    core = core_rate()
    if core and core.get("total"):
        lines.append(f"Core phrases {core['at']}: {core['passed']} of {core['total']} passed.")
        spoken.append(f"The core phrase check passed {core['passed']} of {core['total']}.")
    if week:
        calls = sum(r["calls"] for r in week.values())
        tokens = sum(r["tokens"] for r in week.values())
        lines.append(f"Brain use, last 7 days: {calls} requests, about {tokens // max(1, calls)} tokens each.")
        for key, label in PROVIDERS:
            row = week.get(key, {"calls": 0, "tokens": 0})
            t = today.get(key, {"calls": 0, "tokens": 0})
            lines.append(f"  {label}: {row['calls']} requests this week, {row['tokens']} tokens; today {t['calls']} requests, {t.get('tokens', 0)} tokens")
        spoken.append("This week " + ", ".join(f"{label} answered {week.get(key, {}).get('calls', 0)}" for key, label in PROVIDERS) + ".")
    else:
        lines.append("No brain requests recorded yet.")
    calls, cap, tokens = advanced_today()
    lines.append(f"Advanced (cloud) today: {calls} of {cap} calls, about {tokens} tokens.")
    return " ".join(spoken), "\n".join(lines)


@tool("jarvis_stats", 'args {} - show the test pass rate, average tokens and which brain answered how often; for "jarvis stats"')
def jarvis_stats(args):
    spoken, full = build()
    print("\n" + full + "\n")
    events.emit("sys", full)
    return spoken or "There are no numbers yet. Run the eval script first."


if __name__ == "__main__":
    print(build()[1])
