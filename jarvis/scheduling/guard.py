"""Distraction guard (opt-in, local). Looks at the focused window every few seconds, sorts it into a category,
and gives a gentle nudge after a long stretch of entertainment or social media. Only minutes per category
are stored, never window titles."""
import random
import re
import shutil
import subprocess
import threading
import time
from datetime import date, datetime

from ..actions import windows
from ..brain import brain
from ..core import config, state
from ..memory import store

POLL = 5
GRACE = 120
NAG_GAP = 3600
FOCUS_LIMIT_MIN = 5
CATEGORIES = ("work", "learning", "music", "entertainment", "social", "other")
DISTRACTING = {"entertainment", "social"}
ASK_PER_HOUR = 6
BATCH = 8
BATCH_GAP = 60

MUSIC_APPS = ("spotify", "rhythmbox", "elisa", "amberol", "strawberry", "youtube music", "ytmusic")
MUSIC_WORDS = ("lyrics", "official audio", "playlist", "mix", "song", "songs", "remix", "lofi", "lo-fi", "music",
               "jukebox", "karaoke", "album", "audio", "soundtrack")
LEARN_WORDS = ("tutorial", "lecture", "course", "explained", "how to", "dsa", "python", "machine learning",
               "interview prep", "algorithm", "data structure", "leetcode", "system design", "java", "sql",
               "full stack", "crash course", "walkthrough", "mit opencourseware", "khan academy",
               "documentation", "programming", "ml", "deep learning", "neural network", "computer science",
               "lesson", "syllabus", "operating system", "database", "javascript", "c++", "react", "physics",
               "maths", "mathematics", "chemistry")
SOCIAL_WORDS = ("instagram", "facebook", "twitter", "tiktok", "snapchat", "reddit", "r/", "/ x", "threads.net",
                "9gag", "pinterest", "reels")
ENTERTAINMENT_WORDS = ("netflix", "prime video", "hotstar", "disney+", "hulu", "crunchyroll", "twitch", "anime",
                       "zee5", "sonyliv", "jiocinema", "youtube shorts", "shorts", "gameplay", "trailer", "vlog",
                       "funny", "memes", "meme", "movie", "episode", "web series", "season ")
GAME_APPS = ("steam", "lutris", "heroic", "minecraft", "epicgames", "bottles", "vlc", "mpv", "celluloid")
WORK_APPS = ("code", "vscodium", "kate", "konsole", "terminal", "pycharm", "idea", "okular", "libreoffice",
             "obsidian", "jupyter", "kwrite", "dolphin", "antigravity", "gedit", "zathura", "evince")
WORK_WORDS = ("github", "stack overflow", "stackoverflow", "docs", "documentation", "geeksforgeeks", "w3schools",
              "coursera", "vtu", "college", "university", "notion", "overleaf", "colab", "kaggle", "gitlab",
              "syllabus", "assignment", "classroom", "moodle", ".pdf", "chatgpt")
BROWSERS = ("firefox", "chrome", "chromium", "brave", "vivaldi", "zen", "librewolf", "edge")

NUDGES = [
    "Hey {pet}, that is about {mins} minutes of screen fun. {plan}Maybe a short stretch, then back to it?",
    "{pet}, quick heads up: {mins} minutes on that already. {plan}You are doing great, just keep an eye on the clock.",
    "Friendly nudge, {pet}. {mins} minutes have flown by. {plan}Ready to switch gears?",
    "{pet}, I do not want to nag, but it has been {mins} minutes. {plan}Want me to set a reminder for later?",
]
FOCUS_NUDGES = [
    "{pet}, focus mode is on and that is {mins} minutes off track. {plan}Let us get back to it.",
    "Focus mode check, {pet}: {mins} minutes away from your work. {plan}You can do this.",
]
_asked = {}
_queue = []
_ask_times = []
_words_cache = {}
_flush = {"day": "", "secs": {}, "at": 0.0}
_thread = [None]


def _study_words():
    return tuple(w.strip().lower() for w in config.get("STUDY_KEYWORDS").split(",") if w.strip())


def _has(words, text):
    """True if any word or phrase appears in text as whole words."""
    pattern = _words_cache.get(words)
    if pattern is None:
        pattern = _words_cache[words] = re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in words) + r")(?![a-z0-9])")
    return bool(pattern.search(text))


def rule_verdict(app, title):
    """A category from the local rules, or None when the title is ambiguous."""
    a, t = str(app or "").lower(), str(title or "").lower()
    if any(m in a for m in MUSIC_APPS):
        return "music"
    on_youtube = "youtube" in t
    if on_youtube and "youtube music" in t:
        return "music"
    study = LEARN_WORDS + _study_words()
    if _has(SOCIAL_WORDS, t) and not _has(("tutorial", "course", "lecture"), t):
        return "social"
    if _has(ENTERTAINMENT_WORDS, t) and not _has(study, t):
        return "entertainment"
    if any(g in a for g in GAME_APPS):
        return "entertainment"
    if on_youtube:
        if _has(MUSIC_WORDS, t):
            return "music"
        return "learning" if _has(study, t) else None
    if _has(_study_words() + ("tutorial", "lecture", "course"), t):
        return "learning"
    if any(w in a for w in WORK_APPS) or _has(WORK_WORDS, t):
        return "work"
    if any(b in a for b in BROWSERS) and t.strip() and not _has(("new tab", "gmail", "inbox"), t):
        return None
    return "other"


def classify(app, title):
    """The category now. Ambiguous titles count as other until the next batched question answers them."""
    verdict = rule_verdict(app, title)
    if verdict is not None:
        return verdict
    key = str(title)[:100]
    if key in _asked:
        return _asked[key]
    if key not in _queue and len(_queue) < 20:
        _queue.append(key)
    return "other"


def resolve_queue():
    """One cloud question for all waiting titles. Does nothing without the cloud setting or past the hourly limit."""
    if not _queue:
        return
    now = time.time()
    _ask_times[:] = [t for t in _ask_times if now - t < 3600]
    if not config.flag("GUARD_USE_CLOUD", True) or len(_ask_times) >= ASK_PER_HOUR \
            or (_ask_times and now - _ask_times[-1] < BATCH_GAP):
        return
    batch, _queue[:] = _queue[:BATCH], _queue[BATCH:]
    _ask_times.append(now)
    listing = "\n".join(f"{i}. {t}" for i, t in enumerate(batch, 1))
    reply = brain.ask("Classify each window title as one word: work, learning, music, entertainment, social or "
                      "other. Educational videos and documentation are learning. Answer one line per title like "
                      "'1 learning'.\n" + listing, 12 * len(batch) + 10)
    for num, word in re.findall(r"(\d+)\W+(" + "|".join(CATEGORIES) + ")", reply.lower()):
        if 0 < int(num) <= len(batch):
            _asked[batch[int(num) - 1]] = word
    for t in batch:
        _asked.setdefault(t, "other")


class Tracker:
    """Counts distracting time with a grace period for short breaks, and decides when to nudge."""

    def __init__(self):
        self.acc = 0.0
        self.gap = 0.0
        self.last_nag = 0.0

    def tick(self, category, dt, now, limit_min, quiet=False):
        if category in DISTRACTING:
            self.acc += dt
            self.gap = 0.0
        else:
            self.gap += dt
            if self.gap >= GRACE:
                self.acc = 0.0
        if quiet or self.acc < limit_min * 60 or now - self.last_nag < NAG_GAP:
            return None
        mins = int(self.acc // 60)
        self.last_nag = now
        self.acc = 0.0
        return mins


def planned():
    """What the user said they meant to do today, from a reminder or a note, as a short sentence."""
    from ..memory import notes
    from . import reminders
    study = re.compile(r"\b(study|dsa|assignment|exam|project|submit|revise|practice|homework)\b", re.I)
    for r in reminders.pending():
        if datetime.fromisoformat(r["due"]).date() == date.today() and study.search(r["text"]):
            return f"You planned to {r['text']} today. "
    for text in notes.for_today():
        if study.search(text):
            return f"Your note for today says {text[:60]}. "
    return ""


def enabled():
    flag = state.get("guard")
    return config.flag("DISTRACTION_GUARD") if flag is None else bool(flag)


def limit_minutes():
    if float(state.get("focus_until") or 0) > time.time():
        return FOCUS_LIMIT_MIN
    try:
        return max(1, int(config.get("DISTRACTION_LIMIT_MIN", "25")))
    except ValueError:
        return 25


def on_break():
    return float(state.get("break_until") or 0) > time.time()


def _record(category, dt):
    """Add seconds to today's minutes per category; written to the database about once a minute."""
    day = date.today().isoformat()
    if _flush["day"] != day:
        flush()
        _flush["day"] = day
    _flush["secs"][category] = _flush["secs"].get(category, 0.0) + dt
    if time.time() - _flush["at"] > 60:
        flush()


def flush():
    secs, _flush["secs"] = _flush["secs"], {}
    _flush["at"] = time.time()
    if not secs:
        return
    with store.db() as con:
        for cat, s in secs.items():
            con.execute("INSERT INTO screen_minutes(day, category, minutes) VALUES(?,?,?) "
                        "ON CONFLICT(day, category) DO UPDATE SET minutes=minutes+excluded.minutes",
                        (_flush["day"] or date.today().isoformat(), cat, s / 60))


def minutes_today():
    flush()
    with store.db() as con:
        return {r["category"]: r["minutes"] for r in con.execute(
            "SELECT category, minutes FROM screen_minutes WHERE day=?", (date.today().isoformat(),))}


def nudge(mins):
    pet = config.PET_NAME or "hey"
    focus = float(state.get("focus_until") or 0) > time.time()
    line = random.choice(FOCUS_NUDGES if focus else NUDGES).format(pet=pet, mins=mins, plan=planned())
    line = " ".join(line.split())
    if shutil.which("notify-send"):
        subprocess.run(["notify-send", "Jarvis", line], timeout=5)
    from ..voice import voice
    voice.say(line)


def start():
    """Start the watcher thread once. It sleeps cheaply while the guard is off."""
    if _thread[0] and _thread[0].is_alive():
        return
    tracker = Tracker()

    def loop():
        last = time.time()
        while True:
            if not enabled():
                time.sleep(30)
                last = time.time()
                continue
            time.sleep(POLL)
            now = time.time()
            dt, last = min(now - last, POLL * 3), now
            try:
                win = windows.active_window(max_age=POLL - 1)
                if win is None:
                    if not windows.available():
                        state.update(guard=False)
                    continue
                category = classify(*win)
                resolve_queue()
                _record(category, dt)
                mins = tracker.tick(category, dt, now, limit_minutes(), quiet=on_break() or state.get("muted"))
                if mins:
                    nudge(mins)
            except Exception as e:
                print(f"  (distraction guard check failed: {type(e).__name__})")

    _thread[0] = threading.Thread(target=loop, daemon=True)
    _thread[0].start()
