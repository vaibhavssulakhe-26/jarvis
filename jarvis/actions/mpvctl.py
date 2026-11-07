"""One mpv process, controlled over its IPC socket. Falls back to the browser when mpv is missing."""
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..core import config

VIDEO_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
AUDIO_FORMAT = "bestaudio/best"
_state = {"proc": None}


def socket_path():
    return config.runtime_file("mpv.sock")


def available():
    return config.get("PLAYER", "mpv").lower() == "mpv" and shutil.which("mpv") is not None


def send(*command):
    """Send one command to the running mpv. Returns its reply, or None when mpv is not running."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.5)
            s.connect(str(socket_path()))
            s.sendall((json.dumps({"command": list(command)}) + "\n").encode())
            buf = b""
            while b"\n" not in buf:
                chunk = s.recv(4096)
                if not chunk:
                    break
                buf += chunk
            for line in buf.splitlines():
                data = json.loads(line)
                if "error" in data:
                    return data
    except (OSError, ValueError):
        return None
    return {}


def running():
    return send("get_property", "pid") is not None


def _ytdl_path():
    if shutil.which("yt-dlp"):
        return []
    local = Path(sys.executable).parent / "yt-dlp"
    return [f"--script-opts=ytdl_hook-ytdl_path={local}"] if local.exists() else []


def _start(url, audio):
    cmd = ["mpv", f"--input-ipc-server={socket_path()}", "--idle=yes", "--no-terminal", "--force-window=" + ("no" if audio else "yes"),
           "--ytdl-format=" + (AUDIO_FORMAT if audio else VIDEO_FORMAT)] + (["--vid=no"] if audio else []) + _ytdl_path() + [url]
    _state["proc"] = subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        if running():
            return
        time.sleep(0.1)


def load(url, audio=False):
    """Play url in the same mpv window, starting mpv if it is not running. Music is audio only."""
    if not running():
        _start(url, audio)
        return
    send("set_property", "vid", "no" if audio else "auto")
    send("set_property", "ytdl-format", AUDIO_FORMAT if audio else VIDEO_FORMAT)
    send("loadfile", url, "replace")
    if not audio:
        send("set_property", "force-window", "yes")


def active():
    """True while something is loaded in mpv."""
    reply = send("get_property", "path")
    return bool(reply) and reply.get("error") == "success"


def pause(on=True):
    send("set_property", "pause", on)


def stop():
    send("quit")


def volume(change):
    send("add", "volume", change)


def seek(seconds):
    send("seek", seconds, "relative")
