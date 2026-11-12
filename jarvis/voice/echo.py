"""Tells the user's voice from Jarvis's own output while it speaks or mpv plays. The microphone level during output is learned (its echo),
and only audio clearly louder than that, for a few blocks in a row, counts as the user talking over it. After the output stops there is a
short cooldown so the tail of the echo is ignored."""
import re

MARGIN = 1.8
MIN_LEVEL = 0.03
LEARN_BLOCKS = 5
LOUD_BLOCKS = 3
COOLDOWN = 0.4
STOP_WORDS = re.compile(r"^(?:please )?(?:jarvis )?(?:stop(?: it| that| talking| playing| the (?:music|video|song))?|quiet|enough|shut up|"
                        r"pause(?: it| the (?:music|video|song))?|be quiet|ruko|चुप)$", re.I)


class EchoGate:
    def __init__(self):
        self.floor = 0.0
        self.learned = 0
        self.run = 0
        self.active = False
        self.ended = 0.0

    def feed(self, rms, output_on, now):
        """True when the user is clearly speaking over the output."""
        if not output_on:
            if self.active:
                self.active, self.ended = False, now
                self.floor, self.learned, self.run = 0.0, 0, 0
            return False
        self.active = True
        if now - self.ended < COOLDOWN:
            return False
        if self.learned < LEARN_BLOCKS:
            self.learned += 1
            self.floor = rms if self.floor == 0.0 else 0.8 * self.floor + 0.2 * rms
            return False
        if rms > max(MIN_LEVEL, self.floor * MARGIN):
            self.run += 1
            if self.run >= LOUD_BLOCKS:
                self.run = 0
                return True
            return False
        self.run = 0
        self.floor = 0.9 * self.floor + 0.1 * rms
        return False


def is_stop_phrase(text):
    return bool(STOP_WORDS.match(re.sub(r"[^\w\s]", "", str(text).lower()).strip()))
