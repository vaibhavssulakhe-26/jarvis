"""Local first: the offline model answers chat and simple questions. The cloud ("advanced") is used only when the user asks for it
or the work is heavy, it is counted per day, and it sees only the context it needs."""

import re
import threading
import time
from datetime import datetime

from ..core import config, jsonfile
from ..core.errors import Ask

ASK_BELOW = 10
CLOUD_TURNS = 2
CLOUD_CHARS = 400

USER_WORDS = re.compile(r"\b(?:use advanced|go advanced|advanced mode|think (?:much )?harder?|think hard|go deep(?:er)?|think deeply|use the cloud)\b", re.I)
HEAVY_WORDS = re.compile(r"\b(?:debug|traceback|stack ?trace|openscad|refactor|"
                         r"(?:write|create|build|make|generate)\b.{0,30}\b(?:code|script|program|function|class|website|app|module)|"
                         r"research|summari[sz]e (?:this|the|that) (?:document|paper|pdf|article|file))\b", re.I)
MULTI_STEP = re.compile(r"\b(?:and then|after that|step by step|first\b.{3,60}\bthen)\b", re.I)
FAILED_LINE = re.compile(r"^(?:\(offline\)|no brain answered|still nothing|the cloud brains|advanced (?:did not|is used up)|i tried .{1,40}, it failed)", re.I)

_local = threading.local()


def _t():
    """The state of the request this thread is handling. Another thread (a summary, a routine) never inherits it."""
    if not hasattr(_local, "turn"):
        _local.turn = {"active": False, "forced": False, "approved": False, "text": ""}
    return _local.turn


def begin(text=""):
    _t().update(active=True, forced=bool(USER_WORDS.search(str(text))), approved=False, text=str(text))


def end():
    _t().update(active=False, forced=False, approved=False)


def forced():
    return _t()["forced"]


def is_heavy(text):
    t = str(text)
    return bool(HEAVY_WORDS.search(t))


def is_multi_step(text):
    return bool(MULTI_STEP.search(str(text)))


def daily():
    try:
        return int(config.get("ADVANCED_DAILY", "40"))
    except ValueError:
        return 40


def today(name):
    """Today's {"calls", "tokens"} for a provider or counter name in data/usage.json (counts only, never text)."""
    data = jsonfile.read(config.DATA / "usage.json", None, dict) or {}
    row = (data.get(datetime.now().strftime("%Y-%m-%d")) or {}).get(name) or {}
    return {"calls": int(row.get("calls", 0)), "tokens": int(row.get("tokens", 0))}


def used():
    return today("advanced")["calls"]


def left():
    return max(0, daily() - used())


def replay(text):
    """The user said yes to spending a call: the request runs again with approval."""
    _t().update(active=True, forced=bool(USER_WORDS.search(str(text))), approved=True, text=str(text))


def _wait_for_yes():
    """Park the request in the shared yes / no question. False for a command from the phone, which has no such question."""
    from ..core import main
    if getattr(main.REMOTE, "gate", None):
        return False
    main.PENDING.clear()
    main.PENDING.update({"action": "advanced_confirm", "args": {"text": _t()["text"]}, "until": time.time() + 60})
    return True


def budget():
    """'' when a cloud call may go ahead. A sentence when the day's calls are used up or cannot be asked about. Raises Ask when fewer than
    ten are left and the user has not said yes for this request (only during a typed or spoken turn, never for background work)."""
    n = left()
    if n <= 0:
        return "Advanced is used up for today"
    turn = _t()
    if n < ASK_BELOW and not turn["approved"]:
        if turn["active"] and _wait_for_yes():
            raise Ask(f"I have {n} advanced call{'s' if n != 1 else ''} left today. Use one on this? Say yes or no.")
        return "Advanced is nearly used up"
    return ""


def ambient(messages):
    """True when the last thing said is noise or a failure line, which never goes to the cloud."""
    from ..voice import stt
    last = next((str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"), "")
    plain = re.sub(r"[^\w\s]", "", last).strip()
    return not plain or (len(last) < 200 and stt.is_hallucination(last)) or bool(FAILED_LINE.match(last.strip()))


def cloud_view(messages):
    """What the cloud gets: the system text, the last two turns of history without failure lines, each cut short, and the request itself."""
    if not messages:
        return messages
    head = [m for m in messages[:1] if m.get("role") == "system"]
    body = messages[len(head):]
    last, rest = body[-1:], body[:-1]
    rest = [m for m in rest if m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)
            and not FAILED_LINE.match(m["content"].strip())]
    rest = [{"role": m["role"], "content": m["content"][:CLOUD_CHARS]} for m in rest[-2 * CLOUD_TURNS:]]
    return head + rest + last
