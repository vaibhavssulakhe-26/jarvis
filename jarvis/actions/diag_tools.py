"""Voice tools for diagnostics, the request traces and the offline model."""
from .. import doctor, traces
from ..brain import brain
from ..core import config
from . import events
from .tools import tool


@tool("run_diagnostics", 'args {} - check the microphone, wake word, keys, offline model, tools, voice and memory and say what needs fixing; for "run diagnostics"')
def run_diagnostics(args):
    results = doctor.run()
    text = doctor.report(results)
    print("\n" + text + "\n")
    events.emit("sys", text)
    return doctor.summary(results)


@tool("show_failures", 'args {} - list the last ten requests that failed or that you had to repeat or correct; for "show my failures"')
def show_failures(args):
    rows = traces.failures(10)
    if not rows:
        return "No failed or corrected requests in my traces."
    text = "\n".join(traces.describe(r) for r in rows)
    print("\n" + text + "\n")
    events.emit("sys", text)
    first = rows[0]
    why = "you corrected it" if first.get("corrected") else first.get("reason") or "it failed"
    return f"I found {len(rows)} failed or corrected requests, the list is on screen. The latest was {first.get('heard', '')[:50]}, because {why}."


@tool("which_model", 'args {} - say which brain and offline model are in use; for "which model are you using"')
def which_model(args):
    offline = brain.ollama_model_in_use()
    if config.offline():
        return f"I am in offline mode and using {offline} on this laptop."
    return f"My main brain is {brain.MODEL} on Groq, with OpenRouter next and {offline} as the offline backup."


@tool("run_benchmark", 'args {} - run the 30 test phrases and report the average and slowest latency and tokens; for "run the benchmark"')
def run_benchmark(args):
    from .. import bench
    summary = bench.run()
    bench.save(summary)
    text = bench.describe(summary)
    print("\n" + text + "\n")
    events.emit("sys", text)
    return f"{summary['passed']} of {summary['total']} phrases routed correctly, average {summary['avg_ms']} milliseconds, slowest typical {summary['p95_ms']}."
