"""Checks the proactive chat limits, quiet hours and back-off with a fake clock. Nothing is spoken.
Run: python scripts/proactive_check.py"""
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

scratch = tempfile.mkdtemp(prefix="jarvis-proactive-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
os.environ["QUIET_START"] = "23:00"
os.environ["QUIET_END"] = "07:00"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.core import main, state  # noqa: E402
from jarvis.scheduling import digest, proactive  # noqa: E402

bad = []
MIN = 60.0


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


class Clock:
    def __init__(self, hour=10):
        self.t = datetime(2026, 3, 4, hour, 0).timestamp()

    def __call__(self):
        return self.t

    def advance(self, minutes):
        self.t += minutes * MIN


def make(hour=10, busy=""):
    clock, said = Clock(hour), []
    state.update(proactive=None, quiet_until=0.0, touched_at=0.0, guard=False, activity="idle")
    chatter = proactive.Chatter(clock=clock, speak=said.append, is_busy=lambda: busy_now[0])
    busy_now[0] = busy
    return clock, said, chatter


busy_now = [""]


def run(clock, chatter, minutes, step=1):
    for _ in range(0, minutes, step):
        clock.advance(step)
        chatter.tick()


os.environ["PROACTIVE"] = "off"
clock, said, c = make()
run(clock, c, 300)
check("off by default says nothing", not said)

os.environ["PROACTIVE"] = "normal"
clock, said, c = make()
run(clock, c, 19)
check("nothing before the idle time", not said)
run(clock, c, 2)
check("first line once idle for 20 minutes", len(said) == 1, str(len(said)))
c.touch()
run(clock, c, 19)
check("talking to Jarvis resets idle", len(said) == 1)

clock, said, c = make()
for _ in range(600):
    clock.advance(1)
    c.tick()
hour_max = max(sum(1 for t in c.spoken if now - 3600 < t <= now) for now in list(c.spoken))
check("never more than 3 lines in any hour at normal", hour_max <= 3, str(hour_max))

os.environ["PROACTIVE"] = "low"
clock, said, c = make()
spoken_at = []
for _ in range(400):
    clock.advance(1)
    before = len(said)
    c.tick()
    if len(said) > before:
        spoken_at.append(clock.t)
        c.touch()
gaps = [b - a for a, b in zip(spoken_at, spoken_at[1:])]
check("low speaks at most once an hour", all(g >= 3600 for g in gaps) and len(said) >= 2, str(gaps))

os.environ["PROACTIVE"] = "normal"
clock, said, c = make(hour=22)
run(clock, c, 55)
check("silent after 23:00 quiet hours start", all(datetime.fromtimestamp(t).hour < 23 for t in c.spoken), str(c.spoken))
n = len(said)
run(clock, c, 6 * 60)
check("silent through the night", len(said) == n)
clock, said, c = make(hour=7)
check("quiet hours end at 07:00", c.allowed() == "not idle" or c.allowed() is None)

for why in ("speaking", "focus guard", "digest"):
    clock, said, c = make(busy=why)
    run(clock, c, 120)
    check(f"silent while {why}", not said)
clock, said, c = make()
clock.advance(30)
state.update(guard=True)
c.is_busy = proactive.busy
check("focus guard blocks it", c.allowed() == "focus guard", str(c.allowed()))
state.update(guard=False)
digest.RUNNING.set()
check("morning digest blocks it", c.allowed() == "digest", str(c.allowed()))
digest.RUNNING.clear()
check("free again afterwards", c.allowed() is None, str(c.allowed()))

clock, said, c = make()
run(clock, c, 21)
first = len(said)
run(clock, c, 16)
run(clock, c, 16)
check("second line comes when the first was ignored", len(said) == 2, str(len(said)))
run(clock, c, 90)
check("backs off after two ignored lines", len(said) == 2, str(len(said)))
check("back-off lasts hours", c.silent_until - clock.t > 2 * 3600 - 60 * 95)
run(clock, c, 4 * 60)
check("speaks again after the back-off", len(said) >= 3, str(len(said)))

clock, said, c = make()
run(clock, c, 21)
c.touch()
run(clock, c, 25)
check("answering a line avoids the back-off", c.silent_until == 0.0 and len(said) >= 2)

clock, said, c = make()
state.update(quiet_until=clock.t + 2 * 3600)
run(clock, c, 119)
check("stop talking for two hours holds", not said)
run(clock, c, 30)
check("talks again after the two hours", bool(said))

lines = set()
clock, said, c = make()
for _ in range(40):
    lines.add(c.line())
check("lines vary", len(lines) >= 8, str(len(lines)))
check("no emoji or placeholders", all("{" not in l and l.isascii() for l in lines))

spoken = []
main.voice.say = spoken.append
os.environ["PROACTIVE"] = "off"
state.update(proactive=None)
main._handle("be chattier")
check("be chattier turns it on", proactive.level() == "low", proactive.level())
main._handle("be chattier")
check("chattier again reaches normal", proactive.level() == "normal")
main._handle("be quieter")
check("be quieter steps down", proactive.level() == "low")
main._handle("stop talking for two hours")
check("stop talking sets a quiet period", float(state.get("quiet_until")) > 0, str(spoken[-1:]))
sys.exit(1 if bad else 0)
