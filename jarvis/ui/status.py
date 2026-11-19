"""What the new window shows about Jarvis, taken from the real voice and brain state and never from a timer. No Qt here, so the checks can feed it
made-up snapshots."""
import time
from dataclasses import dataclass

from ..actions import events
from ..brain import local
from ..core import config, state

STATES = ("idle", "listening", "thinking", "speaking", "error", "offline")
ERROR_SECONDS = 5
THINK_SECONDS = 60
TIER_SECONDS = 20
ADVANCED_TIERS = ("advanced", "strong", "fast")


@dataclass
class Snapshot:
    paused: bool = False
    muted: bool = False
    speaking: bool = False
    hearing: bool = False
    thinking: bool = False
    error: bool = False
    offline: bool = False
    online: bool = True
    tier: str = ""
    activity: str = ""
    level: float = 0.0
    out_level: float = 0.0
    warming: bool = False


def resolve_state(s):
    """One of STATES. A fault outranks everything, then no brain, then what Jarvis is doing right now."""
    if s.error:
        return "error"
    if s.offline:
        return "offline"
    if s.speaking:
        return "speaking"
    if s.thinking:
        return "thinking"
    if s.hearing and not s.paused:
        return "listening"
    return "idle"


class Tracker:
    """Listens to the event bus for the things the state file does not hold: a recent failure, the last tier and what Jarvis is busy with."""

    def __init__(self):
        self.error_until = 0.0
        self.tier = ""
        self.tier_at = 0.0
        self.activity = ""
        self.activity_at = 0.0

    def on_event(self, kind, text):
        now = time.time()
        if kind == "sys" and any(w in text.lower() for w in ("error", "stopped", "failed")):
            self.error_until = now + ERROR_SECONDS
        elif kind == "tier":
            self.tier, self.tier_at = text, now
        elif kind in ("tool", "route"):
            self.activity, self.activity_at = text[:60], now
        elif kind == "you":
            self.activity, self.activity_at = "heard you", now


def cloud_levels():
    from ..brain import brain
    return {name: brain.provider_state(name)[0] for name in ("groq", "openrouter", "ollama")}


def snapshot(tracker, levels=None):
    """The live snapshot. `levels` (provider name to ok, idle or bad) is passed in so it is read twice a second, not every frame."""
    from ..voice import voice
    now = time.time()
    st = state.read()
    levels = levels if levels is not None else cloud_levels()
    cloud = [levels.get(n) for n in ("groq", "openrouter")]
    all_bad = all(v == "bad" for v in levels.values())
    offline = config.offline() or all_bad
    return Snapshot(
        paused=bool(st["paused"]), muted=bool(st["muted"]), speaking=voice.SPEAKING.is_set(),
        hearing=bool(getattr(events, "hearing", False)),
        thinking=st["activity"] == "thinking" and now - float(st["activity_at"]) < THINK_SECONDS,
        error=now < tracker.error_until, offline=offline,
        online=not offline and any(v == "ok" for v in cloud),
        tier=tracker.tier if now - tracker.tier_at < TIER_SECONDS else "",
        activity=tracker.activity if now - tracker.activity_at < 30 else "",
        level=events.level, out_level=events.out_level, warming=local.warming())


def mic_label(s):
    if s.paused:
        return "asleep"
    if s.muted:
        return "muted"
    return "hearing you" if s.hearing else "on"


def brain_label(s):
    """Local or advanced: the tier of the last answer for a short while, else what the brain mode makes the usual choice."""
    if s.warming:
        return "local, warming up"
    if s.offline:
        return "local" if config.offline() else "offline"
    if s.tier in ADVANCED_TIERS:
        return "advanced"
    if s.tier:
        return "local"
    return "advanced" if config.brain_mode() == "hybrid" else "local"


def connection_label(s):
    if config.offline():
        return "offline (by choice)"
    if s.offline:
        return "offline"
    return "online" if s.online else "local only"


def state_label(name):
    return {"idle": "Ready", "listening": "Listening", "thinking": "Thinking", "speaking": "Speaking", "error": "Something went wrong",
            "offline": "Offline"}[name]


def greeting(now=None):
    """'Good evening, Vibe': the time of day and the name from the saved profile (a nickname first), or just the greeting when there is no name."""
    from datetime import datetime
    hour = (now or datetime.now()).hour
    word = "Good morning" if 5 <= hour < 12 else "Good afternoon" if 12 <= hour < 18 else "Good evening"
    name = config.PET_NAME or config.SHORT_NAME
    return f"{word}, {name}" if name else word
