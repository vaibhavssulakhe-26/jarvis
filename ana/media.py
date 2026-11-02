"""Music and video: YouTube Music, YouTube, and the media player controls."""
import re
import shutil
import subprocess
import threading
import time
from urllib.parse import quote

from . import apps, voice
from .tools import ToolError, _browser, _launch, heard_recently, tool


@tool("media", 'args {"do": "play_pause, play, pause, next or previous"} - control the music player')
def media(args):
    cmds = {"play_pause": "play-pause", "play": "play", "pause": "pause", "next": "next", "previous": "previous"}
    cmd = cmds.get(str(args.get("do", "")).lower().strip())
    if cmd is None:
        raise ToolError("I can play, pause, skip or go back.")
    if shutil.which("playerctl") is None:
        raise ToolError("Media control needs playerctl. Install it with: sudo dnf install playerctl")
    subprocess.run(["playerctl", cmd], timeout=5)
    return "Done."


def _youtube_id(query):
    result = [""]

    def go():
        try:
            import yt_dlp
            opts = {"quiet": True, "no_warnings": True, "extract_flat": True,
                    "skip_download": True, "socket_timeout": 8}
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info("ytsearch1:" + query, download=False)
            for entry in (info or {}).get("entries") or []:
                vid = str((entry or {}).get("id", ""))
                if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
                    result[0] = vid
                    return
        except Exception as e:
            print(f"  (video lookup failed: {type(e).__name__})")

    worker = threading.Thread(target=go, daemon=True)
    worker.start()
    worker.join(12)
    return result[0]


def _resume_later(delay):
    def go():
        time.sleep(delay)
        if shutil.which("playerctl"):
            try:
                subprocess.run(["playerctl", "-p", "chromium,chrome,firefox", "play"],
                               capture_output=True, timeout=5)
            except (OSError, subprocess.SubprocessError):
                pass
    threading.Thread(target=go, daemon=True).start()


@tool("play_media", 'args {"service": "youtube_music or youtube", "query": "<song, artist or video>"} - start playing music or a video; use an empty query ONLY to resume what is already playing in an open player; if the user asks to play something unnamed such as the first video, use ask instead')
def play_media(args):
    service = str(args.get("service", "youtube_music")).lower()
    query = str(args.get("query", "")).strip()[:120]
    music = "music" in service or "youtube" not in service
    label = "YouTube Music" if music else "YouTube"
    if not query:
        found = apps.find_app(label)
        if found and shutil.which("gio"):
            _launch(["gio", "launch", found[1]])
        else:
            _browser("https://music.youtube.com" if music else "https://www.youtube.com")
        _resume_later(9)
        return f"Opening {label}. I will try to press play for you."
    if query.lower().strip(" .") in {"music", "song", "songs", "a song", "video", "videos", "something", "anything", "some music"}:
        raise ToolError("Which song or artist should I play?")
    if not heard_recently(query):
        raise ToolError("I am not sure what you want me to play. Which song or video?")
    voice.say(f"Looking that up on {label}.")
    vid = _youtube_id(query)
    if vid:
        base = "https://music.youtube.com/watch?v=" if music else "https://www.youtube.com/watch?v="
        _browser(base + vid)
        _resume_later(7)
        return f"Playing {query} on {label}. If it does not start by itself, press play once."
    _browser(("https://music.youtube.com/search?q=" if music
              else "https://www.youtube.com/results?search_query=") + quote(query))
    return f"I opened the {label} search for {query}. I cannot press play on that page yet."
