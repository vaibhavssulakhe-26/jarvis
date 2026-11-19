"""Room noise never reaches the brain: 15 ambient fragments, heard with and without a follow-up window, cost no brain call, no chat message and no
command, and each one is logged as dropped for the Activity page. Accepted utterances are logged with their reason. Run: python scripts/ambient_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

tmp = tempfile.mkdtemp(prefix="jarvis-ambient-")
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402

from jarvis.actions import events  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.memory import threads  # noqa: E402
from jarvis.voice import ears, gate, voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:200] if detail and not ok else ""))
    if not ok:
        bad.append(name)


FRAGMENTS = ["Da da da da da", "Hmm", "I suppose", "Mm-hmm.", "Uh", "la la la la", "Thanks for watching!", "you", "Oh", "Okay okay okay",
             "ha ha ha", "so", "hmm hmm", "Subtitles by the Amara.org community", "yeah yeah yeah yeah"]
check("there are 15 fragments", len(FRAGMENTS) == 15)

calls, commands, chat, hear = [], [], [], []
threads.attach()
threads.changed.append(lambda kind, info: chat.append(info) if kind == "message" else None)
events.listeners.append(lambda kind, text: hear.append(text) if kind == "hear" else None)


def counted(name):
    return lambda *a, **k: calls.append(name) or (None, None)


e = ears.Ears.__new__(ears.Ears)
e._init_echo()
e.followup, e.expect, e.awake_until, e.via_wake = 6.0, False, 0.0, False
e._reset_wake = lambda: None
import queue  # noqa: E402
e.q = queue.Queue()
e.suppress = False
e.on_command = lambda text, via: commands.append(text) or core.handle(text, via)
current = {"text": ""}


def hear_fragment(text, source, output=False):
    current["text"] = text
    with mock.patch.object(ears.stt, "transcribe", lambda a: current["text"]), mock.patch.object(ears.time, "sleep", lambda s: None), \
            mock.patch.object(voice, "wait", lambda: None), mock.patch.object(voice, "say", lambda *a, **k: None), \
            mock.patch.object(ears, "media_playing", lambda: False), mock.patch.object(ears.reminders, "active", lambda: None):
        e._handle(np.zeros(16000, dtype=np.float32), source == "wake", False, source, output)


with mock.patch.object(brain, "route", counted("route")), mock.patch.object(brain, "_groq", counted("groq")), \
        mock.patch.object(brain, "_groq_tools", counted("groq_tools")), mock.patch.object(brain, "_groq_stream", counted("stream")), \
        mock.patch.object(brain, "generate", counted("generate")), mock.patch.object(brain, "chat", counted("chat")), \
        mock.patch.object(brain, "tool_turn", counted("tool_turn")):
    for text in FRAGMENTS:
        for source, output in (("followup", False), ("wake", False), ("followup", True), ("barge", False)):
            hear_fragment(text, source, output)
    check("no ambient fragment reached the command handler", not commands, str(commands[:3]))
    check("0 brain calls for 60 dropped hearings", not calls, str(calls[:5]))
    check("0 chat messages for them", not chat and not threads.current()["messages"], str(chat[:2]))
    check("each hearing is logged as dropped", len(hear) == 60 and all(h.startswith("dropped (") for h in hear), f"{len(hear)} {hear[:2]}")

    del hear[:]
    e.on_command = lambda text, via: commands.append(text) or False
    hear_fragment("the weather is nice today I think", "barge")
    hear_fragment("what is happening over there", "followup", output=True)
    hear_fragment("yes", "followup")
    check("a sentence with no wake word and no window is dropped", hear[0].startswith("dropped (no wake word)"), hear[0])
    check("a sentence captured while sound played is dropped", hear[1].startswith("dropped (captured while sound was playing)"), hear[1])
    check("a bare yes inside the follow-up window is accepted and logged as such", hear[2].startswith("accepted (follow-up)"), hear[2])
    check("the two dropped sentences cost no command", commands == ["yes"], str(commands))

# accepted utterances, each with the reason
del hear[:], commands[:]
for text, source, want in (("open the browser please", "wake", "wake word"), ("what time is it", "ptt", "push-to-talk"),
                           ("could you open the browser", "followup", "follow-up"), ("Jarvis open the browser", "barge", "wake word")):
    hear_fragment(text, source)
check("wake, push-to-talk, follow-up and a spoken name are accepted with the right reason",
      [h.split(")")[0] for h in hear] == ["accepted (wake word", "accepted (push-to-talk", "accepted (follow-up", "accepted (wake word"], str(hear))
check("a one word reply from a person who said the wake word is not filler", gate.judge("stop", "wake")[0])
check("hallucinated text is dropped even with the wake word", not gate.judge("Thanks for watching!", "wake")[0])
check("push-to-talk accepts short speech", gate.judge("next", "ptt")[0])

# the window is one turn: used up by the first sound
e.phase, e.loud, e.awake_until, e.thr = None, 0, __import__("time").time() + 5, 0.02


class Quiet:
    def predict(self, block):
        return {"w": 0.0}


e.oww, e.pre, e.noise, e.n, e.reported = Quiet(), __import__("collections").deque(maxlen=3), [], 1, True
e.cool_until, e.debug, e.wake_thr, e.debug_at = 0.0, False, 0.4, 0.0
loud = np.full(1280, 3000, dtype=np.int16)
with mock.patch.object(ears, "media_playing", lambda: False), mock.patch.object(ears.events, "set_level"), mock.patch.object(ears.mpvctl, "ducked", lambda: False), \
        mock.patch.object(ears.mpvctl, "duck", lambda: None), mock.patch.object(ears.mpvctl, "playing", lambda: False):
    for _ in range(3):
        e._idle(loud, 0.1, __import__("time").time())
check("the first sound uses up the window", e.phase == "record" and e.awake_until == 0.0 and e.source == "followup", f"{e.phase} {e.awake_until} {e.source}")

print("\n" + ("all passed" if not bad else f"{len(bad)} failed"))
sys.exit(1 if bad else 0)
