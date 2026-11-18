"""A stand-in for handctl: a bridge.py with the same four commands whose "viewer" is a small process holding a real Unix socket.
make(folder) builds <folder>/bridge.py, <folder>/.venv/bin/python and <folder>/models. Set FAKE_LOG to a file to record every command and
FAKE_MODE to busy (the viewer never comes up) or refuse (every command fails)."""
import os
import sys
from pathlib import Path

BRIDGE = '''import os, socket, subprocess, sys, time
from pathlib import Path
run = Path(os.environ["XDG_RUNTIME_DIR"]) / "handctl"
sock = run / "holo.sock"
args = sys.argv[1:]
cmd, arg = args[0], " ".join(args[1:])
mode = os.environ.get("FAKE_MODE", "")


def log(text):
    with open(os.environ["FAKE_LOG"], "a") as f:
        f.write(text + "\\n")


def alive():
    s = socket.socket(socket.AF_UNIX)
    s.settimeout(0.3)
    try:
        s.connect(str(sock))
        return True
    except OSError:
        return False
    finally:
        s.close()


if cmd == "serve":
    run.mkdir(exist_ok=True)
    sock.unlink(missing_ok=True)
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(sock))
    srv.listen(2)
    srv.settimeout(0.2)
    (run / "models.txt").write_text("\\n".join(sorted(p.stem for p in (Path(__file__).parent / "models").iterdir())))
    while sock.exists() and not (run / "quit").exists():
        try:
            srv.accept()[0].close()
        except OSError:
            pass
    sock.unlink(missing_ok=True)
    (run / "quit").unlink(missing_ok=True)
    sys.exit(0)

log(cmd + (" " + arg if arg else ""))
if mode == "refuse":
    print("busy")
    sys.exit(1)
if cmd == "open":
    if not alive() and mode != "busy":
        (run / "quit").unlink(missing_ok=True)
        log("serve")
        subprocess.Popen([sys.executable, __file__, "serve"], start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("ok")
elif cmd == "close":
    if not alive():
        print("holo viewer not reachable: no viewer")
        sys.exit(1)
    (run / "quit").write_text("")
    print("ok")
elif alive():
    print("ok")
else:
    print("holo viewer not reachable: no viewer")
    sys.exit(1)
'''


def make(folder):
    folder = Path(folder)
    (folder / "models").mkdir(parents=True, exist_ok=True)
    (folder / ".venv" / "bin").mkdir(parents=True, exist_ok=True)
    py = folder / ".venv" / "bin" / "python"
    if not py.exists():
        py.symlink_to(sys.executable)
    (folder / "bridge.py").write_text(BRIDGE, encoding="utf-8")
    return folder
