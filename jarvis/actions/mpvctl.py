"""One mpv process, controlled over its IPC socket. Falls back to the browser when mpv is missing."""
import json
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from ..core import config

VIDEO_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
AUDIO_FORMAT = "bestaudio"
GRAPHICS_ARGS = "--gpu-api=opengl"
LOG_LIMIT = 200_000
START_WAIT = 6.0
EXIT_GRACE = 2.0
_state = {"proc": None}


def socket_path():
    return config.runtime_file("mpv.sock")


def log_path():
    return config.runtime_file("mpv.log")


def extra_args():
    """MPV_ARGS from .env replaces the default graphics flag; set it empty to pass nothing."""
    return shlex.split(config.get("MPV_ARGS", GRAPHICS_ARGS))


def _open_log():
    path = log_path()
    try:
        if path.stat().st_size > LOG_LIMIT:
            path.unlink()
    except OSError:
        pass
    return open(path, "ab")


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
    """Launch mpv and wait for its socket. Returns False, after logging the exit code once, when mpv dies or stays silent."""
    cmd = ["mpv", f"--input-ipc-server={socket_path()}", "--idle=once", "--input-terminal=no", "--msg-level=all=warn", "--force-window=" + ("no" if audio else "yes"),
           "--ytdl-raw-options=force-ipv4=", "--ytdl-format=" + (AUDIO_FORMAT if audio else VIDEO_FORMAT)] \
        + (["--vid=no"] if audio else []) + extra_args() + _ytdl_path() + [url]
    with _open_log() as log:
        log.write(("\n--- " + time.strftime("%H:%M:%S") + " " + url + "\n").encode())
        log.flush()
        proc = subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
    _state["proc"] = proc
    answered = False
    for step in range(int((START_WAIT + EXIT_GRACE) * 10)):
        code = proc.poll()
        if code is not None:
            if code != 0:
                print(f"  (mpv exited with code {code})")
                return False
            return True
        if not answered and running():
            answered = True
            waited = step
        if answered and step - waited >= EXIT_GRACE * 10:
            return True
        if not answered and step >= START_WAIT * 10:
            break
        time.sleep(0.1)
    if answered:
        return True
    print("  (mpv did not answer on its socket)")
    try:
        proc.kill()
    except OSError:
        pass
    return False


def load(url, audio=False):
    """Play url in the same mpv window, starting mpv if it is not running. Music is audio only. False when mpv could not start."""
    if not running():
        return _start(url, audio)
    send("set_property", "vid", "no" if audio else "auto")
    send("set_property", "ytdl-format", AUDIO_FORMAT if audio else VIDEO_FORMAT)
    send("loadfile", url, "replace")
    if not audio:
        send("set_property", "force-window", "yes")
    return True


def active():
    """True while something is loaded in mpv."""
    reply = send("get_property", "path")
    return bool(reply) and reply.get("error") == "success"


def playing():
    """True while mpv has something loaded and is not paused."""
    if not active():
        return False
    reply = send("get_property", "pause")
    return bool(reply) and reply.get("data") is False


def pause(on=True):
    send("set_property", "pause", on)


def stop():
    send("quit")


def volume(change):
    send("add", "volume", change)


def seek(seconds):
    send("seek", seconds, "relative")
