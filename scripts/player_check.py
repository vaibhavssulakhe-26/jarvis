"""Checks the mpv player with a fake mpv socket: one process, next in the same window, voice controls, search retry.
No real mpv, browser or network. Run: python scripts/player_check.py"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

scratch = tempfile.mkdtemp(prefix="jarvis-player-")
os.environ["JARVIS_DATA"] = scratch
os.environ["XDG_STATE_HOME"] = scratch
os.environ["XDG_RUNTIME_DIR"] = scratch
os.environ.pop("PLAYER", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import mpvctl, play, tools  # noqa: E402,F401
from jarvis.core import main  # noqa: E402

bad = []
commands, spawned, searches, spoken, opened = [], [], [], [], []
server = {"sock": None}


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def serve():
    path = str(mpvctl.socket_path())
    if os.path.exists(path):
        os.remove(path)
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(path)
    s.listen(5)
    server["sock"] = s

    def loop():
        while True:
            try:
                conn, _ = s.accept()
            except OSError:
                return
            with conn:
                data = json.loads(conn.makefile().readline() or "{}")
                commands.append(data.get("command"))
                conn.sendall(b'{"event":"idle"}\n{"error":"success","data":1}\n')
    threading.Thread(target=loop, daemon=True).start()


def fake_popen(cmd, **kw):
    spawned.append(cmd)
    serve()
    return mock.Mock()


def item(i, title, channel, mins, views):
    return {"id": f"{i:011d}", "title": title, "channel": channel, "duration": mins * 60, "views": views}


RESULTS = [item(1, "Lofi beat - Official Audio", "Lofi Girl", 3, 5000000), item(2, "Lofi chill mix", "Chill", 4, 900000),
           item(3, "Lofi study beats", "Beats", 3, 400000)]
LEARN = [item(4, "Binary Trees explained", "Abdul Bari", 25, 800000), item(5, "Trees tutorial", "NeetCode", 30, 700000)]


def fake_search(query, n=8):
    searches.append(query)
    return list(LEARN if "tutorial" in query else RESULTS)


def say(text):
    del spoken[:]
    del commands[:]
    with mock.patch.object(play, "search", fake_search), mock.patch.object(mpvctl.subprocess, "Popen", fake_popen), \
            mock.patch.object(mpvctl.shutil, "which", lambda n: "/usr/bin/" + n), mock.patch.object(mpvctl.time, "sleep", lambda s: None), \
            mock.patch.object(play, "_browser", lambda url: opened.append(url)), \
            mock.patch.object(main.voice, "say", lambda t: spoken.append(str(t))), \
            mock.patch.object(main.brain, "think", lambda *a: searches.append("BRAIN")), \
            mock.patch.object(main.brain, "chat", lambda *a: searches.append("BRAIN")):
        main._recent.clear()
        main._handle(text)
    return spoken[-1] if spoken else ""


def sent(name):
    return [c for c in commands if c and c[0] == name]


play._state.update(results=[], i=0, at=0.0, ask=None)
out = say("play a lofi song")
check("first play starts one mpv", len(spawned) == 1 and "Lofi Girl" in out, out)
check("mpv gets the ipc socket in the runtime dir", any(str(mpvctl.socket_path()) in a for a in spawned[0]))
check("music is audio only, no window", "--vid=no" in spawned[0] and "--force-window=no" in spawned[0])
check("the first ranked result is loaded", spawned[0][-1].endswith(RESULTS[0]["id"]), spawned[0][-1])
check("the browser is not used", not opened)

for phrase in ("next", "play next", "play the next one", "next video", "next song", "another one"):
    play._state.update(i=0, at=time.time())
    before = len(searches)
    out = say(phrase)
    check(f"{phrase!r} loads the next saved result in the same mpv",
          len(sent("loadfile")) == 1 and len(spawned) == 1 and RESULTS[1]["id"] in sent("loadfile")[0][1], str(commands))
    check(f"{phrase!r} is never a search", len(searches) == before, str(searches[before:]))

play._state.update(results=[], i=0, at=0.0, ask=None)
spawned.clear()
out = say("play a video on binary trees")
check("learning videos switch the same mpv to video", ["set_property", "vid", "auto"] in commands and not spawned, str(commands))
play._state["kind"] = "music"
say("another one")
check("switching to music turns video off", ["set_property", "vid", "no"] in commands or "last one" in spoken[-1], str(commands))

play._state.update(results=RESULTS, i=0, at=time.time())
for phrase, expect in (("pause", ["set_property", "pause", True]), ("resume", ["set_property", "pause", False]),
                       ("stop playing", ["quit"]), ("louder", ["add", "volume", 10]), ("quieter", ["add", "volume", -10]),
                       ("skip forward 30 seconds", ["seek", 30, "relative"]), ("go back", ["seek", -30, "relative"])):
    say(phrase)
    check(f"{phrase!r} controls mpv", expect in commands, str(commands))

server["sock"].close()
os.remove(str(mpvctl.socket_path()))
out = say("pause")
check("pause with no player is not sent anywhere", not commands)

del searches[:]
calls = []


def flaky(query, n):
    calls.append(1)
    if len(calls) == 1:
        raise OSError("network")
    return [item(9, "Song", "Artist", 3, 1000)]


with mock.patch.object(play, "_fetch", flaky):
    got = play.search("x")
check("one network error is retried", got and len(calls) == 2, str(got))
del calls[:]
with mock.patch.object(play, "_fetch", mock.Mock(side_effect=OSError("down"))) as dead:
    got = play.search("x")
check("two failures give None", got is None and dead.call_count == 2)
with mock.patch.object(play, "search", lambda q, n=8: None), mock.patch.object(play.mpvctl, "available", lambda: False):
    try:
        play.start("play a lofi song")
        line = ""
    except tools.ToolError as e:
        line = str(e)
check("a failed search gives one friendly line", "cannot reach YouTube" in line, line)

with mock.patch.dict(os.environ, {"PLAYER": "browser"}):
    check("PLAYER=browser keeps the old behaviour", not mpvctl.available())
with mock.patch.object(mpvctl.shutil, "which", lambda n: None):
    check("no mpv installed means the browser path", not mpvctl.available())
sys.exit(1 if bad else 0)
