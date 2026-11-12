"""Vague play requests: search YouTube metadata, pick one result, open it, and keep the rest for "next"."""
import math
import re
import threading
import time

from ..core import config
from . import mpvctl
from .tools import ToolError, _browser, tool

RESULTS = 8
SESSION_SECONDS = 1800
ASK_SECONDS = 30
MPV_TRIES = 3
DEFAULT_CHANNELS = "freeCodeCamp,Abdul Bari,take U forward,NeetCode,Apna College"
MUSIC_WORDS = {"song", "songs", "music", "track", "tracks", "lofi", "playlist", "remix", "beats"}
FILLER = {"a", "an", "the", "some", "any", "me", "one", "something", "anything", "video", "videos", "song", "songs",
          "music", "track", "tracks", "on", "about", "of", "for", "to", "please", "play", "youtube"}
ARTICLES = {"a", "an", "the", "some", "any", "me", "one", "something", "anything", "video", "videos", "please", "play"}
TEACH_WORDS = ("tutorial", "lecture", "course", "explained", "crash course", "full course", "for beginners")
BAD_MUSIC = ("reaction", "cover", "karaoke", "slowed", "reverb", "8d", "nightcore", "tutorial", "how to")
MIN_SCORE = -1.0
_state = {"results": [], "i": 0, "at": 0.0, "kind": "", "topic": "", "music": False, "ask": None, "now": None}


def study_channels():
    return [c.strip().lower() for c in config.get("STUDY_CHANNELS", DEFAULT_CHANNELS).split(",") if c.strip()]


def parse(text):
    """Split a spoken request into (kind, topic, youtube_music). The topic is empty when none was named."""
    t = re.sub(r"[^\w\s']", " ", text.lower())
    t = re.sub(r"^\s*(?:please\s+)?play\b", " ", t)
    music = bool(re.search(r"\byoutube music\b|\byt music\b", t))
    t = re.sub(r"\b(?:on|in|from) (?:youtube music|youtube|yt music|yt)\b", " ", t)
    words = t.split()
    topic_words = [w for w in words if w not in FILLER]
    topic = " ".join(topic_words)
    if re.search(r"\b(?:video|videos|something|anything|one)\s+(?:on|about|for)\b", t) or \
            re.search(r"\b(?:tutorial|lecture|course)\b", t):
        kind = "learning"
    elif re.search(r"\bvideos?\b", t):
        kind = "video"
    elif set(words) & MUSIC_WORDS or "song" in t:
        kind = "music"
    else:
        kind = "music"
    if kind == "music":
        topic = " ".join(w for w in words if w not in ARTICLES) if topic_words else ""
    return kind, topic, music


def query_for(kind, topic):
    return f"{topic} tutorial" if kind == "learning" else topic


def _fetch(query, n):
    import yt_dlp
    opts = {"quiet": True, "no_warnings": True, "extract_flat": True, "skip_download": True, "socket_timeout": 8}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    found = []
    for e in (info or {}).get("entries") or []:
        vid = str((e or {}).get("id", ""))
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            found.append({"id": vid, "title": str(e.get("title") or ""),
                          "channel": str(e.get("channel") or e.get("uploader") or ""),
                          "duration": e.get("duration") or 0, "views": e.get("view_count") or 0,
                          "live": bool(e.get("is_live")) or e.get("live_status") in ("is_live", "is_upcoming")})
    return found


def search(query, n=RESULTS):
    """Metadata only, no download. Returns a list of {id, title, channel, duration, views}, or None when the network failed twice."""
    for attempt in (1, 2):
        out = []

        def go():
            try:
                out.append(_fetch(query, n))
            except Exception as e:
                print(f"  (video lookup failed: {type(e).__name__})")

        worker = threading.Thread(target=go, daemon=True)
        worker.start()
        worker.join(15)
        if out:
            return out[0]
    return None


def score(item, kind, channels, query=""):
    title, channel = item["title"].lower(), item["channel"].lower()
    mins = (item["duration"] or 0) / 60
    views = item["views"] or 0
    pts = 0.0
    if item.get("live"):
        pts -= 30
    if 0 < mins < 1:
        pts -= 5
    if kind == "learning":
        pts += 3 if 10 <= mins <= 90 else 1 if 5 <= mins < 10 else -2 if mins > 180 else 0
        pts += 2 if any(w in title for w in TEACH_WORDS) else 0
        pts += 4 if any(c in channel for c in channels) else 0
        pts += min(3.0, math.log10(views + 1) / 2)
    elif kind == "music":
        official = "official" in title or "vevo" in channel or channel.endswith("- topic")
        pts += 2 if official else 0
        pts += 1 if 1.5 <= mins <= 10 else -2 if mins > 15 and "mix" not in query else 0
        pts += 1 if "mix" in title and not item.get("live") else 0
        pts -= 2 if any(w in title for w in BAD_MUSIC) else 0
    else:
        pts += min(3.0, math.log10(views + 1) / 2)
    return pts


def rank(items, kind, query=""):
    """Best first. Only candidates that pass the ranking stay in the queue; live streams stay at the end as a last resort."""
    channels = study_channels()
    scored = sorted(((score(it, kind, channels, query), it) for it in items), key=lambda pair: -pair[0])
    passed = [it for pts, it in scored if pts >= MIN_SCORE and not it.get("live")]
    streams = [it for _, it in scored if it.get("live")]
    return (passed + streams) or [it for _, it in scored[:1]]


def now():
    """(item, index in the queue) for what mpv is playing, from the same state the queue pointer uses. None when mpv is idle."""
    if not mpvctl.active():
        return None
    item = _state.get("now")
    results = _state["results"]
    if item is None or item not in results:
        return {}, -1
    return item, results.index(item)


def music_video():
    return config.get("MUSIC_VIDEO", "false").lower() in ("1", "true", "yes", "on")


def _open(item):
    """Open item and return what actually started. In mpv, a candidate that fails to start is replaced by the next saved one, up to three."""
    if mpvctl.available():
        results = _state["results"]
        start = results.index(item) if item in results else _state["i"]
        for pos in range(start, min(start + MPV_TRIES, len(results))):
            if mpvctl.load("https://www.youtube.com/watch?v=" + results[pos]["id"], audio=_state["kind"] == "music" and not music_video()):
                _state["i"] = pos
                _state["now"] = results[pos]
                return results[pos]
        raise ToolError(f"I could not get that to play. Details are in {mpvctl.log_path()}.")
    base = "https://music.youtube.com/watch?v=" if _state["music"] else "https://www.youtube.com/watch?v="
    _browser(base + item["id"])
    _state["now"] = item
    return item


def _announce(item):
    who = f" by {item['channel']}" if item["channel"] else ""
    return f"Playing {item['title']}{who}. Say next for another one."


def asking():
    return bool(_state["ask"]) and time.time() < _state["ask"]["until"]


def answer(text):
    """The reply to 'what should I play?': build the request from the kind we were asking about."""
    kind = _state["ask"]["kind"]
    _state["ask"] = None
    return {"query": f"play {kind} on {text}" if kind == "learning" else f"play {text}", "_heard": True}


NEXT = re.compile(r"^(?:please )?(?:play )?(?:the )?(?:next|another|something else|not this)(?: one| video| song| track)?$")


def start(text, music_service=False):
    if NEXT.match(re.sub(r"[^\w\s]", "", text.lower()).strip()):
        return play_next({})
    kind, topic, music = parse(text)
    if not topic:
        _state["ask"] = {"kind": kind, "until": time.time() + ASK_SECONDS}
        raise ToolError({"learning": "Sure. What topic should the video be on?",
                         "video": "Sure. What kind of video?"}.get(kind, "Sure. Any language or artist in mind?"))
    _state["ask"] = None
    query = query_for(kind, topic)
    found = search(query)
    if found is None:
        raise ToolError("I cannot reach YouTube right now. Check the internet and ask me again.")
    items = rank(found, kind, query)
    if not items:
        raise ToolError("I could not find anything for that one. Try other words?")
    _state.update(results=items, i=0, at=time.time(), kind=kind, topic=topic, music=music or music_service)
    return _announce(_open(items[0]))


def active():
    return bool(_state["results"]) and time.time() - _state["at"] < SESSION_SECONDS


@tool("play_next", 'args {} - play the next result of the last play request; for "next", "another one", "not this one"')
def play_next(args):
    if not active():
        raise ToolError("There is nothing to skip. Tell me what to play.")
    if _state["i"] + 1 >= len(_state["results"]):
        raise ToolError(f"That was the last one I found for {_state['topic']}. Ask me for something else.")
    _state["i"] += 1
    _state["at"] = time.time()
    item = _state["results"][_state["i"]]
    return _announce(_open(item))


CONTROLS = {"pause": lambda: mpvctl.pause(True), "resume": lambda: mpvctl.pause(False), "stop": mpvctl.stop,
            "louder": lambda: mpvctl.volume(10), "quieter": lambda: mpvctl.volume(-10),
            "forward": lambda: mpvctl.seek(30), "back": lambda: mpvctl.seek(-30)}


@tool("player_control", 'args {"do": "pause, resume, stop, louder, quieter, forward or back"} - control the video or music Jarvis is playing; for "pause", "resume", "stop playing", "skip forward", "go back"')
def player_control(args):
    which = str(args.get("do") or "").lower()
    if which not in CONTROLS:
        raise ToolError("I can pause, resume, stop, change the volume, skip forward or go back.")
    if not mpvctl.running():
        raise ToolError("Nothing is playing in my player right now.")
    CONTROLS[which]()
    if which == "stop":
        _state["results"] = []
        _state["now"] = None
    return {"pause": "Paused.", "resume": "Playing.", "stop": "Stopped.", "louder": "Louder.", "quieter": "Quieter.",
            "forward": "Thirty seconds ahead.", "back": "Thirty seconds back."}[which]
