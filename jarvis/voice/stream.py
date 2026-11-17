"""Speaks the first sentence of a streamed reply as soon as it is complete, while the rest keeps arriving.
Text goes to the window as "stream" events; the finished reply goes through voice.say with `skip` set to what was already spoken."""
import re

from ..actions import events
from . import speech, voice

END = re.compile(r"[.!?](?:\s|$)")
STRUCTURE = re.compile(r"```|^\s*(?:[-*#|]|\d+[.)])\s|\n")


class Streamer:
    def __init__(self):
        self.text = ""
        self.spoken = 0
        self.closed = False

    def feed(self, delta):
        self.text += delta
        events.emit("stream", delta)
        if self.spoken or self.closed:
            return
        m = END.search(self.text)
        if m is None:
            if len(self.text) > 240:
                self.closed = True
            return
        first = self.text[:m.end()].strip()
        if STRUCTURE.search(first) or len(first) < 12:
            if STRUCTURE.search(first):
                self.closed = True
            return
        spoken = speech.clean(first)
        if spoken and voice.speak_part(spoken):
            self.spoken = 1
        self.closed = True

    def finish(self):
        events.emit("stream_end", "")
