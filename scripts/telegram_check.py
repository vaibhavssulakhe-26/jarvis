"""Telegram bot against a fake Bot API server on localhost: pairing, strangers, confirmation, limits. Run: python scripts/telegram_check.py"""
import io
import json
import os
import re
import sys
import tempfile
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

tmp = Path(tempfile.mkdtemp(prefix="jarvis-telegram-"))
os.environ["JARVIS_DATA"] = str(tmp)
os.environ["XDG_RUNTIME_DIR"] = str(tmp)
os.environ["TELEGRAM"] = "on"
os.environ["TELEGRAM_BOT_TOKEN"] = "123456:FAKE-token-for-the-check"
os.environ["TELEGRAM_RATE"] = "50"
os.environ.pop("TELEGRAM_ALLOW_AGENT", None)
os.environ.pop("BRAIN", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

QUEUE, SENT = [], []
BASE = {"id": 100}


class Fake(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        method = self.path.rsplit("/", 1)[-1]
        if method == "getUpdates":
            off = body.get("offset", 0)
            result = QUEUE[-1:] if off == -1 else [u for u in QUEUE if u["update_id"] >= off]
        elif method == "sendMessage":
            SENT.append((body["chat_id"], body["text"]))
            result = {"message_id": 1}
        else:
            result = True
        data = json.dumps({"ok": True, "result": result}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):
        pass


server = HTTPServer(("127.0.0.1", 0), Fake)
threading.Thread(target=server.serve_forever, daemon=True).start()
os.environ["TELEGRAM_API"] = f"http://127.0.0.1:{server.server_port}"

import re as _re  # noqa: E402
from jarvis import telegram  # noqa: E402
from jarvis.actions import tools  # noqa: E402
from jarvis.core import main as core  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []
ran = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""), file=sys.__stdout__)
    if not ok:
        bad.append(name)


def say(chat, text, kind="private", **extra):
    BASE["id"] += 1
    msg = {"chat": {"id": chat, "type": kind}, "text": text, **extra}
    QUEUE.append({"update_id": BASE["id"], "message": msg})
    n = len(SENT)
    telegram.poll_once(0, sync=True)
    return [t for c, t in SENT[n:] if c == chat]


@tools.tool("test_risky", "args {} - a risky test tool", risk="confirm", describe=lambda a: "I will do the risky thing.")
def test_risky(args):
    ran.append("risky")
    return "The risky thing is done."


@tools.tool("send_test", "args {} - sends something", risk="confirm", describe=lambda a: "I will send it.")
def send_test(args):
    ran.append("send")
    return "Sent."


core.DIRECT.insert(0, (_re.compile(r"^do the risky thing$"), "test_risky", lambda m: {}))
core.DIRECT.insert(0, (_re.compile(r"^send the test$"), "send_test", lambda m: {}))
core.DIRECT.insert(0, (_re.compile(r"^build the test$"), "build_project", lambda m: {"request": "build me a flask app that shows the time"}))

OWNER, STRANGER, GROUP = 5001, 6002, -777
telegram.start.__globals__["_s"]["running"] = True
telegram.new_code()
CODE = telegram._s["code"]
check("status is not paired before pairing", telegram.status() == "not paired" and telegram.pairing_code() == CODE)
check("six digit code", re.fullmatch(r"\d{6}", CODE) is not None)

out = io.StringIO()
with redirect_stdout(out):
    telegram.skip_backlog()
    check("stranger gets no reply before pairing", say(STRANGER, "hello there") == [])
    wrong = "000000" if CODE != "000000" else "111111"
    check("wrong code gets no reply", say(STRANGER, wrong) == [] and not telegram.paired())
    check("code in a group chat does not pair", say(GROUP, CODE, kind="group") == [] and not telegram.paired())
    got = say(OWNER, f"here is the code {CODE}")
    check("the right code pairs the chat", telegram.owner() == OWNER and got and got[0].startswith("Paired"))
    check("owner saved in telegram.json", json.loads((tmp / "telegram.json").read_text()) == {"owner": OWNER})
    check("pairing code gone after pairing", telegram.pairing_code() == "" and telegram.status() == "paired")
    check("stranger still gets nothing", say(STRANGER, "what time is it") == [] and say(STRANGER, CODE) == [])

    got = say(OWNER, "what time is it")
    check("owner command comes back as text", got and re.search(r"\d", got[0]) is not None, str(got))

    got = say(OWNER, "do the risky thing")
    check("risky tool asks first", got and "yes or no" in got[0] and not ran, str(got))
    got = say(OWNER, "yes")
    check("yes runs it", ran == ["risky"] and got and "done" in got[0].lower(), str(got))
    say(OWNER, "do the risky thing")
    got = say(OWNER, "no")
    check("no cancels it", ran == ["risky"] and got and "cancel" in got[0].lower(), str(got))
    check("yes with nothing waiting", "nothing" in say(OWNER, "yes")[0].lower())
    say(OWNER, "do the risky thing")
    say(OWNER, "what time is it")
    check("another command cancels the question", "nothing" in say(OWNER, "yes")[0].lower() and ran == ["risky"])
    core.PENDING.clear()

    got = say(OWNER, "send the test")
    check("sending is refused outright", ran == ["risky"] and got and "phone" in got[0].lower(), str(got))
    got = say(OWNER, "build the test")
    check("coding tasks are off by default", got and "TELEGRAM_ALLOW_AGENT" in got[0], str(got))
    with mock.patch.dict(os.environ, {"TELEGRAM_ALLOW_AGENT": "on"}):
        check("agent gate opens with the setting", telegram.GATE.blocked("build_project") == "")
        check("send stays blocked with the setting", telegram.GATE.blocked("send_test") != "")

    got = say(OWNER, "ok", forward_origin={"type": "user"})
    check("forwarded text is not run", got and "forwarded" in got[0].lower())
    got = say(OWNER, "/start")
    check("/start gives help", got and "/brief" in got[0])
    got = say(OWNER, "/tasks")
    check("/tasks answers", got and "task" in got[0].lower(), str(got))
    got = say(OWNER, "/status")
    check("/status answers", got and "alerts" in got[0], str(got))
    with mock.patch("jarvis.routines.morning.latest", return_value={"text": "# Briefing\nAll quiet.", "spoken": "x"}):
        check("/brief sends the briefing", "All quiet" in say(OWNER, "/brief")[0])
    with mock.patch("jarvis.actions.mpvctl.stop") as stopped, mock.patch("jarvis.voice.voice.stop"):
        check("/stop stops things", say(OWNER, "/stop") == ["Stopped."] and stopped.called)
    check("unknown slash command", "do not know" in say(OWNER, "/nonsense")[0])

    check("notify reaches the owner", telegram.notify("Reminder: test", wait=True) and SENT[-1] == (OWNER, "Reminder: test"))

os.environ["TELEGRAM_RATE"] = "3"
telegram._s["times"].clear()
with redirect_stdout(io.StringIO()):
    replies = [say(OWNER, "what time is it") for _ in range(6)]
check("rate limit warns once then goes quiet", sum(1 for r in replies if r and "minute" in r[0]) == 1 and replies[-1] == [], str(replies))
os.environ["TELEGRAM_RATE"] = "50"
telegram._s["times"].clear()

log = io.StringIO()
with redirect_stdout(log):
    say(OWNER, "my mail is private.person@example.com ok")
check("heard line is masked", "private.person@example.com" not in log.getvalue() and "[email]" in log.getvalue())

with voice.capture() as lines:
    voice.say("quiet line")
check("capture holds lines instead of speaking", lines == ["quiet line"])

server.shutdown()
server.server_close()
log = io.StringIO()
with redirect_stdout(log):
    try:
        telegram.poll_once(0)
        down = None
    except telegram.Down as e:
        down = str(e)
check("a dead API raises Down without the token", down is not None and "FAKE-token" not in down, str(down))
check("token never printed", "FAKE-token" not in log.getvalue())
telegram.unpair()
check("unpair clears the owner", not telegram.paired())
check("off without the setting", (lambda: os.environ.update(TELEGRAM="off") or telegram.status())() == "off")

print("\nall passed" if not bad else f"\n{len(bad)} failed: {bad}", file=sys.__stdout__)
sys.exit(1 if bad else 0)
