"""Phone control over a Telegram bot (TELEGRAM=on). Long polling with plain requests, no framework.

The first private chat that sends the six digit pairing code shown at start becomes the owner (data/telegram.json). Every other chat gets
no reply at all. The owner's messages run through the same router as typed commands, and what Jarvis would have said comes back as text.
Message text is only ever a command string for the router: it is never evaluated, never put in a system prompt and never logged unmasked.
Risky tools are held for a yes or no from the owner chat, and some are not available from the phone at all."""
import hmac
import re
import secrets
import threading
import time
from collections import deque

import requests

from . import redact
from .core import config, jsonfile
from .core.errors import ToolError

API = "https://api.telegram.org"
CHUNK = 3900
MAX_TEXT = 500
CONFIRM_SECONDS = 60
CODE_GUESSES = 5
CODE_WINDOW = 600

# never from the phone, even with a yes: sending, deleting, powering off, installing
NEVER = re.compile(r"^(?:send_|delete_|message_|clear_|forget$|shutdown$|restart$|suspend$|install_|apply_|git_)")
AGENT_TOOLS = {"build_project", "run_project", "stop_project", "fix_last_error", "add_feature", "edit_file", "find_bugs", "explain_file",
               "browse_agent", "make_website", "preview_site", "export_site"}
HELP = ("I am Jarvis. Send a command like you would type it, or use /brief, /email, /tasks, /status and /stop. "
        "Anything risky waits for a yes or no from you.")

_busy = threading.Lock()
_s = {"code": "", "fails": deque(), "times": deque(), "warned": 0.0, "pending": None, "offset": 0, "running": False, "quiet": False}


def path():
    return config.DATA / "telegram.json"


def load():
    return jsonfile.read(path(), {}, dict)


def owner():
    value = load().get("owner")
    return value if isinstance(value, int) else None


def paired():
    return owner() is not None


def token():
    return config.get("TELEGRAM_BOT_TOKEN")


def enabled():
    return config.flag("TELEGRAM") and bool(token()) and not config.offline()


def allow_agent():
    return config.flag("TELEGRAM_ALLOW_AGENT")


def status():
    """'paired', 'not paired' or 'off' (also off when there is no token), for the doctor and the dashboard."""
    if not config.flag("TELEGRAM"):
        return "off"
    return "paired" if paired() else "not paired"


def pairing_code():
    """The code to send to the bot, or '' when already paired or the bot is not running."""
    return "" if paired() or not _s["running"] else _s["code"]


def _base():
    base = (config.get("TELEGRAM_API") or API).rstrip("/")
    if not (base.startswith("https://") or base.startswith("http://127.0.0.1") or base.startswith("http://localhost")):
        return API
    return base


class Down(Exception):
    """The API could not be reached or refused the call. The message never carries the URL, which contains the token."""


def call(method, params=None, wait=10):
    try:
        r = requests.post(f"{_base()}/bot{token()}/{method}", json=params or {}, timeout=wait)
    except requests.RequestException as e:
        raise Down(type(e).__name__)
    if r.status_code in (401, 404):
        raise Down("token refused")
    try:
        data = r.json()
    except ValueError:
        raise Down("bad reply")
    if not isinstance(data, dict) or not data.get("ok"):
        raise Down(f"status {r.status_code}")
    return data.get("result")


def send(chat_id, text):
    text = str(text).strip() or "Done."
    parts = [text[i:i + CHUNK] for i in range(0, len(text), CHUNK)]
    for part in parts[:5]:
        call("sendMessage", {"chat_id": chat_id, "text": part, "disable_web_page_preview": True})


def notify(text, wait=False):
    """Message the owner, if paired. Never raises. Runs in the background unless wait is set."""
    if not enabled() or not paired() or not str(text).strip():
        return False

    def go():
        try:
            send(owner(), text)
        except Down as e:
            print(f"  (telegram: could not send, {e})")
    if wait:
        go()
    else:
        threading.Thread(target=go, daemon=True).start()
    return True


def notify_once(key, text):
    """Like notify, but at most once per day for the key, even across two Jarvis processes."""
    from datetime import date
    from .memory import store
    if not enabled() or not paired() or not store.claim(key, date.today().isoformat()):
        return False
    return notify(text)


# ---------- pairing ----------
def new_code():
    _s["code"] = f"{secrets.randbelow(10 ** 6):06d}"
    _s["fails"].clear()
    return _s["code"]


def announce_code():
    from .actions import events
    line = f"Telegram pairing code: {_s['code']}. Send it to your bot to pair this phone."
    print("  " + line)
    events.emit("sys", line)


def try_pair(chat_id, text):
    """Pair when the message holds the current code. Wrong six digit guesses are counted; too many change the code. Never replies to a miss."""
    found = re.findall(r"(?<!\d)\d{6}(?!\d)", text)
    if not found:
        return False
    now = time.time()
    while _s["fails"] and now - _s["fails"][0] > CODE_WINDOW:
        _s["fails"].popleft()
    if any(hmac.compare_digest(f, _s["code"]) for f in found):
        jsonfile.write(path(), {"owner": chat_id})
        _s["code"] = ""
        print("  (telegram: paired)")
        try:
            send(chat_id, "Paired. You can now send me commands. " + HELP)
        except Down:
            pass
        return True
    _s["fails"].append(now)
    if len(_s["fails"]) >= CODE_GUESSES:
        new_code()
        announce_code()
    return False


def unpair():
    try:
        path().unlink()
    except OSError:
        pass
    _s["pending"] = None


# ---------- what the phone may do ----------
class Gate:
    """Installed on the thread that runs an owner command (main.REMOTE.gate). main asks it before every tool."""

    def blocked(self, action):
        if NEVER.match(action):
            return "I do not do that from the phone. Do it at the laptop."
        from .core import main
        if (action in AGENT_TOOLS or main.agent_of(action) in ("coder", "browser")) and not allow_agent():
            return "Coding and browser tasks are off from the phone. Set TELEGRAM_ALLOW_AGENT=on in the .env file to allow them."
        return ""

    def ask(self, action, args, question):
        _s["pending"] = {"action": action, "args": args, "until": time.time() + CONFIRM_SECONDS}
        return question + " Reply yes or no."


GATE = Gate()


def clean(text):
    text = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", str(text))
    return " ".join(text.split())[:MAX_TEXT]


def route(text, action=None, args=None):
    """Run one command through the normal router with replies captured. Returns the reply text."""
    from .core import main
    from .voice import voice
    main.REMOTE.gate = GATE
    try:
        with voice.capture() as lines:
            if action:
                main.do_tool(action, args or {})
            else:
                main.handle(text)
    except Exception as e:
        print(f"  (telegram command failed: {type(e).__name__})")
        lines = ["That did not work. Something broke on my side."]
    finally:
        main.REMOTE.gate = None
    return "\n".join(str(x) for x in lines) or "Done."


def stop_all():
    from .actions import mpvctl, web_agent
    from .voice import voice
    voice.stop()
    mpvctl.stop()
    web_agent.abort()
    return "Stopped."


def command(name):
    """The reply for a slash command, or None when it is not one."""
    from .actions import tools
    if name in ("start", "help"):
        return HELP
    if name == "stop":
        return stop_all()
    if name == "brief":
        from .routines import morning
        got = morning.latest()
        return (got or morning.build())["text"]
    if name == "email":
        from .routines import maildigest
        return maildigest.digest()["text"]
    if name == "tasks":
        from . import tasks
        return tasks.describe()
    if name == "status":
        from . import alerts
        from .scheduling import reminders
        parts = [tools.TOOLS["system_status"]["fn"]({})]
        parts.append(f"{len(reminders.pending())} pending reminders, {alerts.count()} alerts.")
        return " ".join(parts)
    return None


def resolve(text):
    """A yes or no for the held action. Returns the reply, or None when the message is something else."""
    from .core import main
    pend = _s["pending"]
    words = re.findall(r"[a-z]+", text.lower())
    verdict = main._verdict(words) if len(words) <= 4 else None
    if not pend:
        return "Nothing is waiting for a yes or no." if verdict and len(words) <= 2 else None
    _s["pending"] = None
    if time.time() > pend["until"] or verdict is None:
        return None
    if verdict == "no":
        return "Okay, cancelled."
    return route("", pend["action"], pend["args"])


def process(msg):
    """One incoming message. Returns the reply that was sent, or None when nothing was sent."""
    chat = msg.get("chat") if isinstance(msg, dict) else None
    chat = chat if isinstance(chat, dict) else {}
    cid, text = chat.get("id"), msg.get("text") if isinstance(msg, dict) else None
    if not isinstance(cid, int) or not isinstance(text, str) or chat.get("type") != "private":
        return None
    if owner() is None:
        try_pair(cid, text)
        return None
    if cid != owner():
        return None
    now = time.time()
    times = _s["times"]
    while times and now - times[0] > 60:
        times.popleft()
    limit = max(1, int(config.get("TELEGRAM_RATE", "20") or 20))
    if len(times) >= limit:
        if now - _s["warned"] > 60:
            _s["warned"] = now
            return _reply(cid, "That is a lot of messages. Give me a minute.")
        return None
    times.append(now)
    if msg.get("forward_origin") or msg.get("forward_date"):
        return _reply(cid, "That is a forwarded message, so I treat it as text, not as a command. Type the command yourself.")
    text = clean(text)
    print(f"  (telegram heard: {redact.mask(text)[:80]})")
    if not text:
        return None
    if not _busy.acquire(blocking=False):
        if text.lower().split("@")[0] == "/stop":
            return _reply(cid, stop_all())
        return _reply(cid, "I am still working on the last one.")
    try:
        from .actions import events
        slash = re.match(r"^/(\w+)(?:@\w+)?\b", text)
        reply = None
        if slash:
            try:
                reply = command(slash.group(1).lower())
            except ToolError as e:
                reply = str(e)
            if reply is None:
                reply = "I do not know that command. " + HELP
        else:
            reply = resolve(text)
            if reply is None:
                events.emit("you", "(phone) " + redact.mask(text))
                reply = route(text)
        events.emit("jarvis", reply)
        return _reply(cid, reply)
    finally:
        _busy.release()


def _reply(cid, text):
    try:
        send(cid, text)
    except Down as e:
        print(f"  (telegram: could not reply, {e})")
    return text


def poll_once(wait=25, sync=False):
    """Fetch the waiting updates and handle them. Returns how many arrived. `sync` handles them on this thread (the checks use it)."""
    updates = call("getUpdates", {"offset": _s["offset"], "timeout": wait, "allowed_updates": ["message"]}, wait=wait + 10) or []
    for upd in updates:
        if isinstance(upd, dict) and isinstance(upd.get("update_id"), int):
            _s["offset"] = max(_s["offset"], upd["update_id"] + 1)
            msg = upd.get("message")
            if isinstance(msg, dict):
                if sync:
                    process(msg)
                else:
                    threading.Thread(target=_safe, args=(msg,), daemon=True).start()
    return len(updates)


def _safe(msg):
    try:
        process(msg)
    except Exception as e:
        print(f"  (telegram message failed: {type(e).__name__})")


def skip_backlog():
    """Messages sent while Jarvis was off are dropped, so an old command never runs by surprise."""
    updates = call("getUpdates", {"offset": -1, "timeout": 0}) or []
    if updates and isinstance(updates[-1], dict) and isinstance(updates[-1].get("update_id"), int):
        _s["offset"] = updates[-1]["update_id"] + 1


def loop():
    delay = 2
    skipped = False
    while _s["running"]:
        try:
            if not skipped:
                skip_backlog()
                skipped = True
            poll_once(int(config.get("TELEGRAM_POLL", "25") or 25))
            delay = 2
        except Down as e:
            if str(e) == "token refused":
                print("  (telegram: the bot token was refused, check TELEGRAM_BOT_TOKEN)")
                _s["running"] = False
                return
            if not _s["quiet"]:
                print(f"  (telegram: cannot reach the API, {e}; retrying)")
                _s["quiet"] = True
            time.sleep(delay)
            delay = min(60, delay * 2)
        except Exception as e:
            print(f"  (telegram loop failed: {type(e).__name__})")
            time.sleep(10)


def start():
    """Start the bot thread when TELEGRAM=on and a token is set. Returns True when it started."""
    if config.flag("TELEGRAM") and not token():
        print("  (telegram is on but TELEGRAM_BOT_TOKEN is not set)")
    if not enabled() or _s["running"]:
        return False
    _s["running"] = True
    if not paired():
        new_code()
        announce_code()
    threading.Thread(target=loop, daemon=True).start()
    return True


def stop():
    _s["running"] = False


if __name__ == "__main__":
    import sys
    if "--unpair" in sys.argv:
        unpair()
        print("telegram: not paired")
    else:
        print("telegram:", status(), "| token", "set" if token() else "not set")
