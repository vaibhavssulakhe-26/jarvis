"""Child processes started for the user's projects: tracked, stopped by name, killed when Jarvis exits."""
import atexit
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

_children = {}
STOP_GRACE = 3.0
ENV_KEEP = ("PATH", "HOME", "LANG", "LC_ALL", "DISPLAY", "WAYLAND_DISPLAY", "XDG_RUNTIME_DIR", "XDG_SESSION_TYPE", "QT_QPA_PLATFORM")


def clean_env(**extra):
    """Only the variables a program needs to run. API keys and the rest of .env never reach generated code."""
    env = {k: os.environ[k] for k in ENV_KEEP if k in os.environ}
    env.update({k: str(v) for k, v in extra.items()})
    return env


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def spawn(name, cmd, cwd, env, log):
    """Start cmd in its own process group with output going to the log file. Replaces a process of the same name."""
    stop(name)
    handle = open(log, "ab")
    try:
        proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=handle, stderr=subprocess.STDOUT,
                                start_new_session=True)
    finally:
        handle.close()
    _children[name] = proc
    return proc


def alive(name=None):
    names = [name] if name else list(_children)
    return any(_children.get(n) is not None and _children[n].poll() is None for n in names)


def running():
    return [n for n, p in _children.items() if p.poll() is None]


def get(name):
    return _children.get(name)


def stop(name):
    """Stop one process and its children. True if something was running."""
    proc = _children.pop(name, None)
    if proc is None or proc.poll() is not None:
        return False
    _kill(proc)
    return True


def _kill(proc):
    for sig, wait in ((signal.SIGTERM, STOP_GRACE), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        end = time.time() + wait
        while time.time() < end:
            if proc.poll() is not None:
                return
            time.sleep(0.05)


def stop_all():
    for name in list(_children):
        stop(name)


def wait_port(port, proc=None, timeout=15.0):
    """True once something accepts connections on the port; False if the process exits first or time runs out."""
    end = time.time() + timeout
    while time.time() < end:
        if proc is not None and proc.poll() is not None:
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def tail(path, lines=40, chars=2500):
    try:
        text = Path(path).read_text(errors="replace")
    except OSError:
        return ""
    return "\n".join(text.splitlines()[-lines:])[-chars:]


atexit.register(stop_all)
