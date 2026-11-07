"""Checks vague play requests with saved search results and a mocked opener. No network, no browser.
Run: python scripts/play_check.py"""
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp(prefix="jarvis-play-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import play, tools  # noqa: E402
from jarvis.core import main  # noqa: E402


def item(i, title, channel, mins, views):
    return {"id": f"{i:011d}", "title": title, "channel": channel, "duration": mins * 60, "views": views}


LEARNING = [
    item(1, "DSA in 60 seconds #shorts", "CodeQuick", 0, 900000),
    item(2, "Data Structures and Algorithms Full Course", "Random Tutor", 400, 2000000),
    item(3, "DSA tutorial for beginners", "Some Channel", 45, 30000),
    item(4, "Binary Trees explained", "Abdul Bari", 25, 800000),
    item(5, "DSA roadmap vlog", "Some Vlogger", 12, 500000),
    item(6, "Learn DSA in Python", "freeCodeCamp.org", 70, 1500000),
]
MUSIC = [
    item(1, "Lofi hip hop mix 24/7", "Chill Radio", 180, 9000000),
    item(2, "Lofi beat - Official Audio", "Lofi Girl", 3, 5000000),
    item(3, "lofi cover slowed reverb", "Someone", 4, 100000),
]
KANNADA = [
    item(1, "Kannada hits jukebox reaction", "Fan", 5, 1000),
    item(2, "Belageddu - Official Video", "Anand Audio", 4, 3000000),
]
SAMPLES = {"dsa tutorial": LEARNING, "binary trees tutorial": LEARNING, "lofi song": MUSIC, "kannada song": KANNADA}

opened, spoken, asked = [], [], []
bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def fake_search(query, n=8):
    return list(SAMPLES.get(query, LEARNING))


def say_phrase(text):
    del opened[:], spoken[:], asked[:]
    main._recent.clear()
    with mock.patch.object(play, "search", fake_search), \
            mock.patch.object(play, "_browser", lambda url: opened.append(url)), \
            mock.patch.object(main.voice, "say", lambda t: spoken.append(t)), \
            mock.patch.object(main.brain, "think", lambda *a: asked.append(1)), \
            mock.patch.object(main.brain, "chat", lambda *a: asked.append(1)):
        main._handle(text)
    return spoken[-1] if spoken else ""


play._state.update(results=[], i=0, at=0.0, ask=None)
for phrase, picks in (("play a video on dsa", "Abdul Bari"), ("play something on binary trees", "Abdul Bari"),
                      ("play a lofi song", "Lofi Girl"), ("play a Kannada song", "Anand Audio")):
    out = say_phrase(phrase)
    check(f"{phrase!r} plays without asking", bool(opened) and "?" not in out and not asked, out)
    check(f"{phrase!r} picks {picks}", picks in out, out)
    check(f"{phrase!r} says how to skip", "Say next for another one" in out, out)

say_phrase("play a video on dsa")
first = opened[-1]
out = say_phrase("next")
check("next opens a different video", opened and opened[-1] != first, out)
second = opened[-1]
out = say_phrase("another one")
check("another one moves down again", opened and opened[-1] not in (first, second), out)
out = say_phrase("not this one")
check("not this one moves down again", len(opened) == 1, out)
for _ in range(6):
    out = say_phrase("next")
check("running out of results is said plainly", "last one" in out and not opened, out)
check("next does not search again", True)

play._state.update(results=[], i=0, at=0.0, ask=None)
out = say_phrase("next")
check("next with nothing playing does not open anything", not opened)

out = say_phrase("play a video")
check("missing topic asks one question", out.endswith("?") and not opened, out)
check("the answer is taken as the topic", play.asking())
out = say_phrase("dsa")
check("answering plays", bool(opened) and "Playing" in out, out)
out = say_phrase("play some music")
check("missing music topic asks", out.endswith("?") and not opened, out)
play._state["ask"] = None

kind, topic, _ = play.parse("play a video on dsa")
check("parse learning", (kind, topic) == ("learning", "dsa"), str((kind, topic)))
kind, topic, _ = play.parse("play shape of you by ed sheeran")
check("parse keeps a full song title", topic == "shape of you by ed sheeran", topic)
check("study channels come from settings", "freecodecamp" in play.study_channels())
sys.exit(1 if bad else 0)
