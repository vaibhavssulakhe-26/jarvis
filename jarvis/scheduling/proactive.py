"""Jarvis starts a short chat now and then when you have been quiet for a while. Off unless PROACTIVE is low or normal."""
import random
import threading
import time
from collections import deque
from datetime import datetime

from ..core import config, state
from . import digest, guard, reminders

LEVELS = ("off", "low", "normal")
PER_HOUR = {"low": 1, "normal": 3}
IDLE_MINUTES = {"low": 40, "normal": 20}
MIN_GAP = 15 * 60
BACKOFF = 4 * 3600
MODEL_GAP = 4 * 3600
POLL = 30

LINES = {
    "checkin": ["No activity for {m} minutes. Say a command if you need anything."],
    "break": ["You have been at the screen for {m} minutes. A short break is due.",
              "{m} minutes since you last did anything here. Stand up and drink some water."],
    "study": ["{m} minutes without a command. Say start focus 20 to begin a timer."],
}
MODEL_SYSTEM = ("You are {name}. Say one short factual sentence saying how long the user has been inactive and that a break is due. "
                "No jokes, no encouragement, no emoji.")


def level():
    """off, low or normal: set by voice for now, else PROACTIVE from .env."""
    value = (state.get("proactive") or config.get("PROACTIVE", "off")).lower()
    return value if value in LEVELS else "off"


def busy():
    """Why Jarvis should keep quiet right now, or ''."""
    from ..voice import voice
    if voice.SPEAKING.is_set() or state.get("activity") in ("speaking", "thinking"):
        return "speaking"
    if guard.enabled():
        return "focus guard"
    if digest.RUNNING.is_set():
        return "digest"
    return ""


class Chatter:
    def __init__(self, clock=time.time, speak=None, is_busy=busy, ask=None):
        self.clock = clock
        self.speak = speak
        self.is_busy = is_busy
        self.ask = ask
        self.touched = clock()
        self.spoken = deque()
        self.last_kind = ""
        self.ignored = 0
        self.silent_until = 0.0
        self.model_at = 0.0
        self.spoken_at = 0.0
        self.bag = {}

    def touch(self):
        self.touched = self.clock()

    def last_touch(self):
        return max(self.touched, float(state.get("touched_at") or 0))

    def allowed(self):
        """None when a line may be spoken now, else the reason it may not."""
        now = self.clock()
        lv = level()
        if lv == "off":
            return "off"
        if now < self.silent_until or float(state.get("quiet_until") or 0) > now:
            return "asked to be quiet"
        if reminders.in_quiet(datetime.fromtimestamp(now)):
            return "quiet hours"
        why = self.is_busy()
        if why:
            return why
        if now - self.last_touch() < IDLE_MINUTES[lv] * 60:
            return "not idle"
        while self.spoken and now - self.spoken[0] > 3600:
            self.spoken.popleft()
        if len(self.spoken) >= PER_HOUR[lv] or (self.spoken and now - self.spoken[-1] < MIN_GAP):
            return "too soon"
        return None

    def line(self):
        now = self.clock()
        if self.ask and level() == "normal" and now - self.model_at > MODEL_GAP and random.random() < 0.25:
            self.model_at = now
            text = self.ask(MODEL_SYSTEM.format(name=config.ASSISTANT))
            if text:
                return text.strip()
        kinds = [k for k in LINES if k != self.last_kind]
        self.last_kind = kind = random.choice(kinds)
        if not self.bag.get(kind):
            self.bag[kind] = random.sample(LINES[kind], len(LINES[kind]))
        text = self.bag[kind].pop()
        minutes = max(1, int((now - self.last_touch()) / 60))
        return text.format(m=minutes)

    def tick(self):
        """Speak one line if everything allows it. Returns the line, or None."""
        if self.allowed():
            return None
        now = self.clock()
        # two lines in a row with nothing said to Jarvis in between: back off for a few hours
        self.ignored = self.ignored + 1 if self.spoken_at and self.last_touch() <= self.spoken_at else 0
        if self.ignored >= 2:
            self.silent_until = now + BACKOFF
            self.ignored = 0
            return None
        text = self.line()
        self.spoken.append(now)
        self.spoken_at = now
        self.speak(text)
        return text


def _ask(system):
    from ..brain import brain
    return brain.ask("Say it now.", 60, system=system)


def start():
    from ..voice import voice
    chatter = Chatter(speak=voice.say, ask=_ask)

    def loop():
        time.sleep(60)
        while True:
            try:
                chatter.tick()
            except Exception as e:
                print(f"  (chat check failed: {type(e).__name__})")
            time.sleep(POLL)
    threading.Thread(target=loop, daemon=True).start()
