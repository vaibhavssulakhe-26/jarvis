"""One mpv process, controlled over its IPC socket. Falls back to the browser when mpv is missing."""
import argparse
import atexit
import json
import os
import shlex
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

from ..core import config

VIDEO_FORMAT = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
AUDIO_FORMAT = "bestaudio"
GRAPHICS_ARGS = "--gpu-api=opengl --hwdec=no"
LOG_LIMIT = 200_000
START_WAIT = 6.0
EXIT_GRACE = 2.0
DUCK_LEVEL = 15
_state = {"proc": None, "restore": None}


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


def start_volume():
    """MPV_VOLUME (default 50): mpv's own level, kept below the speakers' limit so a voice carries over it."""
    try:
        return max(0, min(100, int(float(config.get("MPV_VOLUME", "50")))))
    except ValueError:
        return 50


def video_format():
    return config.get("YT_FORMAT", VIDEO_FORMAT) or VIDEO_FORMAT


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
           f"--volume={start_volume()}", "--autofit-larger=80%x80%",
           "--ytdl-raw-options=force-ipv4=", "--ytdl-format=" + (AUDIO_FORMAT if audio else video_format())] \
        + (["--vid=no"] if audio else []) + extra_args() + _ytdl_path() + [url]
    with _open_log() as log:
        log.write(("\n--- " + time.strftime("%H:%M:%S") + " " + url + "\n").encode())
        log.flush()
        proc = subprocess.Popen(cmd, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
    _state["proc"] = proc
    _state["restore"] = None
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
        started = _start(url, audio)
        if started and not audio:
            raise_window()
        return started
    send("set_property", "vid", "no" if audio else "auto")
    send("set_property", "ytdl-format", AUDIO_FORMAT if audio else video_format())
    send("loadfile", url, "replace")
    if not audio:
        send("set_property", "force-window", "yes")
        raise_window()
    return True


def _find_window():
    out = subprocess.run(["kdotool", "search", "--class", "mpv"], capture_output=True, text=True, timeout=3).stdout.split()
    return out[-1] if out else None


def _bring_forward(wait):
    """The window appears only after the stream resolves, so look for it for a while, then activate it."""
    deadline = time.time() + wait
    while time.time() < deadline:
        try:
            win = _find_window()
            if win:
                subprocess.run(["kdotool", "windowactivate", win], capture_output=True, timeout=3)
                return True
        except (OSError, subprocess.SubprocessError):
            return False
        time.sleep(0.5)
    return False


def raise_window(wait=20.0):
    """Put the mpv video window in front of the other windows (kdotool); does nothing without it."""
    if shutil.which("kdotool") is None:
        return None
    thread = threading.Thread(target=_bring_forward, args=(wait,), daemon=True)
    thread.start()
    return thread


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
    """Quit mpv, kill it if it ignores the request, and remove its socket."""
    _state["restore"] = None
    send("quit")
    proc = _state["proc"]
    if proc is not None:
        try:
            proc.wait(timeout=1.0)
        except (subprocess.TimeoutExpired, OSError):
            try:
                proc.kill()
            except OSError:
                pass
        _state["proc"] = None
    if not running():
        try:
            os.unlink(socket_path())
        except OSError:
            pass


atexit.register(stop)


def ducked():
    return _state["restore"] is not None


def duck():
    """Turn mpv down while Jarvis listens, remembering the level. True if mpv was turned down."""
    if ducked():
        return False
    reply = send("get_property", "volume")
    if not reply or not isinstance(reply.get("data"), (int, float)):
        return False
    _state["restore"] = reply["data"]
    send("set_property", "volume", min(DUCK_LEVEL, reply["data"]))
    return True


def unduck():
    level = _state["restore"]
    _state["restore"] = None
    if level is not None:
        send("set_property", "volume", level)


def volume(change):
    if ducked():
        _state["restore"] = max(0, min(130, _state["restore"] + change))
        return
    send("add", "volume", change)


def seek(seconds):
    send("seek", seconds, "relative")


def main(argv=None):
    """Keyboard-shortcut entry: python -m jarvis.actions.mpvctl --pause / --stop / --next"""
    ap = argparse.ArgumentParser(prog="python -m jarvis.actions.mpvctl")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--pause", action="store_true", help="pause or resume the player")
    group.add_argument("--stop", action="store_true", help="stop playing")
    group.add_argument("--next", action="store_true", help="play the next saved result (needs Jarvis running)")
    args = ap.parse_args(argv)
    if args.next:
        from ..core import state
        state.update(command="next", command_at=time.time())
        return 0
    if not running():
        print("nothing is playing")
        return 1
    if args.pause:
        send("cycle", "pause")
    else:
        stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
