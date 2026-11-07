"""Checks what reaches the voice: symbols and links are removed, long or structured text goes to the screen and clipboard.
Nothing is spoken. Run: python scripts/speech_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp(prefix="jarvis-speech-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.voice import speech, voice, voices  # noqa: E402

bad = []
FORBIDDEN = ("asterisk", "slash", "hashtag", "backtick", "underscore", "pipe")


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


CLEAN = {
    "**Done** with *that* task": "Done with that task",
    "## Heading\nSome `code` here": "Heading Some code here",
    "Save to snake_case_name now": "Save to snake case name now",
    "Fish & chips at 50% off": "Fish and chips at 50 percent off",
    "See https://example.com/a/b?c=1 for more": "See link on screen for more",
    "Mail me at someone@example.com please": "Mail me at please",
    "Great job \U0001F389\U0001F44D": "Great job",
    "It's 11:46 PM, isn't it?": "It's 11:46 PM, isn't it?",
    "Pick one [option] {now} | ok": "Pick one option now ok",
    "---": "",
    "- first item\n- second item": "first item second item",
    "a/b and 24/7": "a b and 24 7",
    "well-known fact": "well-known fact",
}
for raw, want in CLEAN.items():
    got = speech.clean(raw)
    check(f"clean {raw!r}", got == want, repr(got))
two = speech.clean("one https://a.com two https://b.com")
check("link on screen is said once", two.count("link on screen") == 1, two)
check("no symbol word can appear", not any(w in speech.clean("*#_`|/\\~^<>=+@").lower() for w in FORBIDDEN) and speech.clean("*#_`|/\\~^<>=+@") == "")

check("short reply is not long", not speech.too_long("It is 11 PM. Time to rest."))
check("code is long", speech.too_long("Here:\n```python\nprint(1)\n```"))
check("a list is long", speech.too_long("Things:\n- one\n- two\n- three"))
check("a table is long", speech.too_long("| a | b |\n| 1 | 2 |"))
check("an email draft is long", speech.too_long("Dear Professor,\n\nI am writing about X.\n\nRegards,\nMe"))
check("six sentences are long", speech.too_long("One. Two. Three. Four. Five. Six."))
check("replies are capped at three sentences", speech.shorten("One. Two. Three. Four.") == "One. Two. Three.")

queued, clips = [], []


def run(text, copied=True):
    del queued[:], clips[:]
    with mock.patch.object(voices, "current_path", lambda: Path("v.onnx")), mock.patch.object(voice, "_queue") as q, \
            mock.patch.object(voice.events, "emit"), mock.patch("jarvis.actions.screen.write_clip", lambda t: clips.append(t) or copied):
        q.put.side_effect = lambda item: queued.append(item[1])
        voice.say(text)
    return queued[0] if queued else ""


out = run("**Hello** there, it's 40% done & fine")
check("say() sends only clean text to the voice", out == "Hello there, it's 40 percent done and fine", out)
draft = "Subject: Extension\n\nDear Professor,\n\nI would like more time.\n\nRegards,\nMe"
out = run(draft)
check("a draft is copied and a short line is spoken", out == speech.DONE and clips == [draft], out)
out = run(draft, copied=False)
check("without a clipboard tool it still says so briefly", out == "Done, it's on your screen.", out)
out = run("```python\nprint('hi')\n```")
check("code is never read out", "print" not in out and out == speech.DONE, out)
out = run("One. Two. Three. Four.")
check("four sentences are cut to three when spoken", out == "One. Two. Three.", out)
out = run(speech.Full("Line one.\nLine two.\n- item\n- item"))
check("text read aloud on request is not replaced", "Line one" in out and out != speech.DONE, out)
out = run("Visit https://example.com/path now")
check("a link is never spoken", "http" not in out and "link on screen" in out, out)
sys.exit(1 if bad else 0)
