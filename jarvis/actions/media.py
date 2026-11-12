"""Music and video: YouTube Music, YouTube, and the media player controls."""
import shutil
import subprocess
import threading
import time

from .. import platform
from . import apps, play
from .tools import ToolError, _browser, _launch, heard_recently, tool


@tool("media", 'args {"do": "play_pause, play, pause, next or previous"} - control the music player')
def media(args):
    cmds = {"play_pause": "play-pause", "play": "play", "pause": "pause", "next": "next", "previous": "previous"}
    cmd = cmds.get(str(args.get("do", "")).lower().strip())
    if cmd is None:
        raise ToolError("I can play, pause, skip or go back.")
    platform.media_control(cmd)
    return "Done."


def _resume_later(delay):
    def go():
        time.sleep(delay)
        try:
            platform.media_control("play", "chromium,chrome,firefox")
        except (OSError, subprocess.SubprocessError, ToolError):
            pass
    threading.Thread(target=go, daemon=True).start()


@tool("play_media", 'args {"service": "youtube_music or youtube", "query": "<what the user asked to play, in their words>"} - start playing music or a video; a vague request is fine, it picks one itself; use an empty query ONLY to resume what is already playing in an open player')
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
    if not args.get("_heard") and not heard_recently(query):
        raise ToolError("I am not sure what you want me to play. Which song or video?")
    return play.start(query, music_service="music" in service and "youtube" in service)
