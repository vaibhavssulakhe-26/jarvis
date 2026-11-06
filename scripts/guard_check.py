"""Prints the guard verdict for sample window titles. No window or network needed. Run: python scripts/guard_check.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.scheduling import guard  # noqa: E402

SAMPLES = [
    ("firefox", "Netflix - Mozilla Firefox", "entertainment"),
    ("firefox", "Instagram - Reels", "social"),
    ("firefox", "YouTube Shorts - funny cats", "entertainment"),
    ("firefox", "Python tutorial for beginners - YouTube", "learning"),
    ("firefox", "MIT 6.006 lecture 3 - YouTube", "learning"),
    ("firefox", "Machine learning course week 2 - YouTube", "learning"),
    ("firefox", "Python documentation - Mozilla Firefox", "work"),
    ("firefox", "Lofi hip hop radio - YouTube", "music"),
    ("spotify", "Spotify Premium", "music"),
    ("steam", "Steam", "entertainment"),
    ("org.kde.konsole", "JARVIS : python - Konsole", "work"),
    ("code", "guard.py - JARVIS - Visual Studio Code", "work"),
    ("firefox", "Some random blog post - Mozilla Firefox", None),
    ("firefox", "Cat videos 2026 - YouTube", None),
]

bad = 0
for app, title, want in SAMPLES:
    got = guard.rule_verdict(app, title)
    mark = "ok  " if got == want else "FAIL"
    bad += got != want
    print(f"{mark} {got or 'ask the brain':<16} {app} | {title}")

t = guard.Tracker()
nudges = [t.tick("entertainment", 60, 10**6 + i * 60, 5) for i in range(30)]
fired = [n for n in nudges if n]
print(("ok  " if len(fired) == 1 else "FAIL") + f" one nudge in 30 minutes of entertainment: {fired}")
bad += len(fired) != 1
sys.exit(1 if bad else 0)
