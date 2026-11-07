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
    "checkin": [
        "Hey {pet}, still alive over there? I was getting lonely.",
        "How is it going? Anything I can take off your plate?",
        "Just checking in. Need anything, or shall I stay quiet?",
        "It has been quiet, so I wondered how your day is going.",
        "{pet}, you have been heads down for a while. All good?",
    ],
    "break": [
        "{pet}, stretch time. Roll your shoulders, sip some water, then back to it.",
        "Quick break? Look away from the screen for a minute, your eyes will thank you.",
        "You have been at it a while. Stand up, walk to the window, come back sharper.",
        "Water check. Have you had any in the last hour?",
    ],
    "study": [
        "Want to do one small thing for your goals today? Even ten minutes counts.",
        "{pet}, how about one tiny study sprint? I can set a twenty minute timer.",
        "Quick one: what is the one thing you want done before you stop today?",
        "If you are stuck, tell me where. Sometimes saying it out loud fixes it.",
    ],
    "joke": [
        "Why do programmers prefer dark mode? Because light attracts bugs.",
        "I would tell you a UDP joke, but you might not get it.",
        "A SQL query walks into a bar, walks up to two tables and asks: can I join you?",
        "Why was the laptop cold? It left its Windows open.",
        "Debugging is being the detective in a crime movie where you are also the culprit.",
        "There are only ten kinds of people: those who understand binary, and those who do not.",
    ],
}
MODEL_SYSTEM = ("You are {name}, a friendly voice companion. Say one short, warm, slightly funny sentence to nudge the "
                "user to take a break or check in. Plain words, no emoji.")


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
        pet = config.PET_NAME
        now = self.clock()
        if self.ask and level() == "normal" and now - self.model_at > MODEL_GAP and random.random() < 0.25:
            self.model_at = now
            text = self.ask(MODEL_SYSTEM.format(name=config.ASSISTANT) + (f" Their pet name is {pet}." if pet else ""))
            if text:
                return text.strip()
        kinds = [k for k in LINES if k != self.last_kind]
        self.last_kind = kind = random.choice(kinds)
        if not self.bag.get(kind):
            self.bag[kind] = random.sample(LINES[kind], len(LINES[kind]))
        text = self.bag[kind].pop()
        # the pet name goes in about half the time, and never as a dangling placeholder
        if "{pet}" in text:
            use = pet and random.random() < 0.5
            text = text.format(pet=pet) if use else text.replace("Hey {pet}, ", "Hey, ").replace("{pet}, ", "")
        return text[0].upper() + text[1:]

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
