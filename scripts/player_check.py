"""Checks the mpv player with a fake mpv socket: one process, next in the same window, voice controls, search retry.
No real mpv, browser or network. Run: python scripts/player_check.py"""
import contextlib
import io
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
                cmd = tuple((data.get("command") or [])[:2])
                value = {("get_property", "volume"): 50, ("get_property", "pause"): False}.get(cmd, 1)
                conn.sendall(b'{"event":"idle"}\n' + json.dumps({"error": "success", "data": value}).encode() + b"\n")
    threading.Thread(target=loop, daemon=True).start()


class FakeProc:
    def __init__(self, code=None):
        self.code = code

    def poll(self):
        return self.code

    def kill(self):
        self.code = -9


modes = {"exit": [], "silent": False}


popen_kw = []


def fake_popen(cmd, **kw):
    spawned.append(cmd)
    popen_kw.append(kw)
    if modes["exit"]:
        return FakeProc(modes["exit"].pop(0))
    if not modes["silent"]:
        serve()
    return FakeProc()


def item(i, title, channel, mins, views):
    return {"id": f"{i:011d}", "title": title, "channel": channel, "duration": mins * 60, "views": views}


def live(i, title):
    return dict(item(i, title, "Lofi Girl", 0, 9000000), live=True)


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
            mock.patch.object(play, "_browser", lambda url: opened.append(url)), mock.patch.object(mpvctl, "raise_window", lambda *a: None), \
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


play._state.update(results=RESULTS, i=0, at=time.time())
mpvctl._state["restore"] = None
del commands[:]
check("duck turns mpv down to the duck level", mpvctl.duck() and ["set_property", "volume", 15] in commands and mpvctl.ducked(), str(commands))
check("a second duck changes nothing", not mpvctl.duck())
del commands[:]
mpvctl.volume(10)
check("louder while ducked changes the level to restore, not the ducked one", not sent("add") and mpvctl._state["restore"] == 60, str(commands))
mpvctl.unduck()
check("unduck restores the remembered level", ["set_property", "volume", 60] in commands and not mpvctl.ducked(), str(commands))
del commands[:]
mpvctl.unduck()
check("unduck with nothing ducked sends nothing", not commands)
check("playing is true for a loaded, unpaused file", mpvctl.playing())

with mock.patch.dict(os.environ, {"MPV_VOLUME": "35"}):
    check("MPV_VOLUME is read", mpvctl.start_volume() == 35)
with mock.patch.dict(os.environ, {"MPV_VOLUME": "loud"}):
    check("a bad MPV_VOLUME falls back to 50", mpvctl.start_volume() == 50)
os.environ.pop("MPV_VOLUME", None)
check("MPV_VOLUME defaults to 50", mpvctl.start_volume() == 50)
with mock.patch.dict(os.environ, {"YT_FORMAT": "best[height<=360]"}):
    check("YT_FORMAT replaces the video format", mpvctl.video_format() == "best[height<=360]")
check("the video format defaults to the tested one", mpvctl.video_format() == mpvctl.VIDEO_FORMAT)

window_calls = []
with mock.patch.object(mpvctl.shutil, "which", lambda n: "/usr/bin/" + n), \
        mock.patch.object(mpvctl, "_find_window", lambda: "{abc}"), \
        mock.patch.object(mpvctl.subprocess, "run", lambda cmd, **kw: window_calls.append(cmd) or mock.Mock(stdout="")):
    check("the video window is brought forward", mpvctl._bring_forward(1.0) and ["kdotool", "windowactivate", "{abc}"] in window_calls, str(window_calls))
with mock.patch.object(mpvctl, "_find_window", lambda: None), mock.patch.object(mpvctl.time, "sleep", lambda s: None), \
        mock.patch.object(mpvctl.time, "time", mock.Mock(side_effect=[0, 0, 5, 50])):
    check("no window means no activation and no hang", not mpvctl._bring_forward(1.0))
with mock.patch.object(mpvctl.shutil, "which", lambda n: None):
    check("without kdotool nothing is attempted", mpvctl.raise_window() is None)

check("music is audio only by default", not play.music_video())
with mock.patch.dict(os.environ, {"MUSIC_VIDEO": "true"}):
    check("MUSIC_VIDEO=true is read", play.music_video())
for phrase in ("play a video of lofi beats", "watch the matrix trailer", "play a video on trees", "show me cat videos"):
    kind = play.parse(phrase if phrase.startswith("play") else "play a video of " + phrase.split(" ", 1)[1])[0]
    check(f"{phrase!r} is a video request", kind in ("video", "learning"), kind)
check("a plain song request stays music", play.parse("play a lovely song")[0] == "music")
loads = []
with mock.patch.object(mpvctl, "available", lambda: True), mock.patch.object(mpvctl, "load", lambda url, audio=False: loads.append(audio) or True):
    play._state.update(results=RESULTS, i=0, kind="music")
    play._open(RESULTS[0])
    with mock.patch.dict(os.environ, {"MUSIC_VIDEO": "1"}):
        play._open(RESULTS[0])
    play._state["kind"] = "video"
    play._open(RESULTS[0])
check("songs are audio only unless MUSIC_VIDEO, videos always open a window", loads == [True, False, False], str(loads))

say("pause")
del commands[:]
for phrase in ("stop playing. Stop playing", "Stop playing, stop playing.", "stop playing stop playing"):
    del commands[:]
    before = len(searches)
    say(phrase)
    check(f"{phrase!r} goes to the direct command", ["quit"] in commands and len(searches) == before, str(commands) + str(searches[before:]))
    serve()
server["sock"].close()
os.remove(str(mpvctl.socket_path()))
out = say("pause")
check("pause with no player is not sent anywhere", not commands)

mix = item(20, "Lofi mix 1 hour", "Chill", 60, 300000)
radio = live(21, "lofi hip hop radio - beats to relax/study to")
order = play.rank([radio, mix, RESULTS[2]], "music", "lofi")
check("music ranking puts the live stream last", order[-1] is radio and order[0] is not radio, str([i["id"] for i in order]))
check("a long mix beats a live stream when it is the only normal result", play.rank([radio, mix], "music", "lofi")[0] is mix)
check("a live stream is kept as the last resort", radio in order)

RUN = [item(30, "Dead one", "A", 3, 1000), item(31, "Also dead", "B", 3, 900), item(32, "Works", "C", 3, 800), item(33, "Spare", "D", 3, 700)]


def play_with(results, **mode):
    modes.update(exit=list(mode.get("exit", [])), silent=mode.get("silent", False))
    server["sock"] = None
    if os.path.exists(str(mpvctl.socket_path())):
        os.remove(str(mpvctl.socket_path()))
    play._state.update(results=list(results), i=0, at=time.time(), kind="music", topic="x", music=False, ask=None)
    del spawned[:]
    lines = io.StringIO()
    with mock.patch.object(mpvctl.subprocess, "Popen", fake_popen), mock.patch.object(mpvctl.shutil, "which", lambda n: "/usr/bin/" + n), \
            mock.patch.object(mpvctl.time, "sleep", lambda s: None), mock.patch.object(mpvctl, "raise_window", lambda *a: None), \
            contextlib.redirect_stdout(lines):
        try:
            got = play._announce(play._open(results[0]))
        except tools.ToolError as e:
            got = "ERR " + str(e)
    return got, lines.getvalue()


got, log = play_with(RUN, exit=[2])
check("the safe graphics flag is on by default", "--gpu-api=opengl" in spawned[0], str(spawned[0]))
check("mpv stderr goes to a log file in the runtime dir, not data", popen_kw[0]["stderr"].name == str(mpvctl.log_path())
      and str(mpvctl.log_path()).startswith(scratch) and "data" not in Path(str(mpvctl.log_path())).parts, str(popen_kw[0]["stderr"]))
check("mpv gets no terminal input", popen_kw[0]["stdin"] == mpvctl.subprocess.DEVNULL and "--input-terminal=no" in spawned[0])
check("the log notes which url was started", "ytdl" in mpvctl.log_path().read_text() or "youtube.com" in mpvctl.log_path().read_text())
with mock.patch.dict(os.environ, {"MPV_ARGS": "--vo=gpu --volume=0"}):
    play_with(RUN)
    check("MPV_ARGS replaces the default flags", "--vo=gpu" in spawned[0] and "--volume=0" in spawned[0] and "--gpu-api=opengl" not in spawned[0], str(spawned[0]))
with mock.patch.dict(os.environ, {"MPV_ARGS": ""}):
    play_with(RUN)
    check("an empty MPV_ARGS passes nothing extra", not any(a.startswith("--gpu") for a in spawned[0]), str(spawned[0]))
got, log = play_with(RUN, exit=[2])
check("mpv launch uses force-ipv4 and the audio format for music", "--ytdl-raw-options=force-ipv4=" in spawned[0] and "--ytdl-format=bestaudio" in spawned[0], str(spawned[0]))
check("a non-zero exit moves quietly to the next candidate", len(spawned) == 2 and "Also dead" in got and spawned[1][-1].endswith(RUN[1]["id"]), got)
check("the exit code is logged once", log.count("exited with code 2") == 1, log)
got, log = play_with(RUN, exit=[2, 1])
check("two failures still reach the third candidate", len(spawned) == 3 and "Works" in got and play._state["i"] == 2, got)
check("each failure logs its own code", "code 2" in log and "code 1" in log, log)
got, log = play_with(RUN, exit=[2, 2, 2, 2])
check("three failures stop with one friendly line", len(spawned) == 3 and got.startswith("ERR I could not get that to play"), got)
check("the failure line names the log once", got.count(str(mpvctl.log_path())) == 1, got)
check("the fourth candidate is never tried", all(not a[-1].endswith(RUN[3]["id"]) for a in spawned))
got, log = play_with(RUN, silent=True)
check("a silent socket counts as a failure and is retried", len(spawned) == 3 and got.startswith("ERR") and "did not answer" in log, got + log)
got, log = play_with(RUN)
check("a healthy start plays the first candidate", len(spawned) == 1 and "Dead one" in got and not log, got + log)

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
