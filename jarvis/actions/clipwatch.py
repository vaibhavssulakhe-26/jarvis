"""Clipboard monitor (opt-in). Notices a copied link, error, code or long text and offers one action by voice.
Nothing is stored: only a hash of the last clip is kept to tell when it changes."""
import hashlib
import re
import shutil
import threading
import time

from ..brain import brain
from ..core import config, state
from . import events
from .screen import looks_secret, read_clip
from .tools import ToolError, tool

POLL = 2
OFFER_GAP = 30
LONG_TEXT = 500
LINK = re.compile(r"^https?://\S+$")
ERROR = re.compile(r"Traceback \(most recent call last\)|\b\w*(?:Error|Exception)\b: |\bcommand not found\b|"
                   r"\bsegmentation fault\b|\bpermission denied\b|\bFAILED\b|error\[E\d+\]|\bat \S+\(\S+:\d+\)", re.I)
CODE = re.compile(r"^\s*(?:def |class |import |from \S+ import |function |const |let |#include|public |if \(|for \()", re.M)
_thread = [None]
_last = {"hash": "", "offered": 0.0}


def enabled():
    flag = state.get("clipwatch")
    return config.flag("CLIPBOARD_MONITOR") if flag is None else bool(flag)


def classify(text):
    """('link' | 'error' | 'code' | 'text', offer sentence), or None when nothing is worth offering."""
    t = text.strip()
    if not t or looks_secret(t):
        return None
    if LINK.match(t):
        return "link", "You copied a link. Want a summary of it?"
    if ERROR.search(t):
        return "error", "That looks like an error. Want me to explain it?"
    if CODE.search(t) and t.count("\n") >= 2:
        return "code", "You copied some code. Want me to explain it?"
    if len(t) >= LONG_TEXT:
        return "text", "That is a long piece of text. Want a summary?"
    return None


@tool("clip_summary", "args {} - summarise the link or long text on the clipboard; used after the clipboard monitor offers it")
def clip_summary(args):
    from ..research import research
    text = read_clip()
    if not text or looks_secret(text):
        raise ToolError("The clipboard has nothing I can summarise.")
    if LINK.match(text.strip()):
        page = research._page_text(text.strip())
        if not page:
            raise ToolError("I could not open that link.")
        text = page
    out = brain.ask("Summarise this in two short spoken sentences:\n" + text[:6000], 150)
    if not out:
        raise ToolError("I could not summarise that right now.")
    return out


@tool("clip_monitor_switch", 'args {"on": true or false} - turn the clipboard monitor on or off; for "turn on clipboard monitor"')
def clip_monitor_switch(args):
    on = args.get("on") in (True, "true", "yes", "on", 1)
    if on and not shutil.which("wl-paste"):
        raise ToolError("I need wl-paste to watch the clipboard.")
    state.update(clipwatch=on)
    if on:
        start()
        return "Clipboard monitor is on. I will offer help with links, errors and code, and never keep what you copy."
    return "Clipboard monitor is off."


def offer(kind, sentence):
    from ..core import main as core
    from . import files
    from ..voice import voice
    if core.PENDING or files.waiting():
        return
    action = "debug_clipboard" if kind in ("error", "code") else "clip_summary"
    args = {"kind": kind} if action == "debug_clipboard" else {}
    core.PENDING.clear()
    core.PENDING.update({"action": action, "args": args, "until": time.time() + 30})
    events.emit("sys", sentence)
    voice.say(sentence)


def start():
    if _thread[0] and _thread[0].is_alive():
        return

    def loop():
        primed = False
        while True:
            time.sleep(POLL if enabled() else 20)
            if not enabled():
                primed = False
                continue
            if state.get("muted") or float(state.get("break_until") or 0) > time.time():
                continue
            try:
                text = read_clip()
                digest = hashlib.sha1(text.encode()).hexdigest() if text else ""
                if not primed:
                    _last["hash"], primed = digest, True
                    continue
                if not digest or digest == _last["hash"]:
                    continue
                _last["hash"] = digest
                found = classify(text)
                if found and time.time() - _last["offered"] > OFFER_GAP:
                    _last["offered"] = time.time()
                    offer(*found)
            except (ToolError, OSError) as e:
                print(f"  (clipboard monitor: {e})")
                time.sleep(60)
            except Exception as e:
                print(f"  (clipboard monitor failed: {type(e).__name__})")
                time.sleep(60)

    _thread[0] = threading.Thread(target=loop, daemon=True)
    _thread[0].start()
