"""Ana: puts the ears, the brain, the tools and the voice together."""
import json
import random
import re
import sys
import threading
import time
from datetime import datetime

from . import apps, brain, companion, config, reminders, state, tools, voice

PENDING = {}
STRONG_YES = {"yes", "yeah", "yep", "yup", "confirm", "confirmed", "proceed", "ahead"}
YES_FILLER = STRONG_YES | {"go", "do", "it", "please", "sir"}
NO_WORDS = {"no", "nope", "cancel", "stop", "never", "mind", "don", "t", "not", "abort", "please", "sir"}
SLOW = re.compile(r"\b(and|then|also|after|before|remind|reminder|draft|email|write|note|find|search|"
                  r"research|create|shut|shutdown|restart|suspend|play|pause|mute|unmute|message|send)\b")
UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
    "sixteen seventeen eighteen nineteen".split())}
TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
        "eighty": 80, "ninety": 90}


def find_number(text):
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        return min(int(m.group(1)), 100)
    total, found = 0, False
    for tok in text.split():
        if tok in UNITS:
            total += UNITS[tok]
            found = True
        elif tok in TENS:
            total += TENS[tok]
            found = True
        elif tok == "hundred":
            total = max(total, 1) * 100
            found = True
    return min(total, 100) if found else None


LAUNCH = {"open_app", "open_folder", "play_media", "open_url", "web_search"}
_recent = {}


def dedupe(plans):
    """Drop repeated actions, and an open-YouTube action when a play action is also there."""
    has_play = any(str(p.get("action")) == "play_media" for p in plans)
    out, seen = [], set()
    for p in plans:
        act = str(p.get("action"))
        args = p.get("args") if isinstance(p.get("args"), dict) else {}
        if has_play and act == "open_app" and "youtube" in str(args.get("name", "")).lower():
            continue
        key = (act, json.dumps(args, sort_keys=True, default=str))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def do_tool(action, args, spoken=""):
    if action in LAUNCH:
        key = (action, json.dumps({k: v for k, v in args.items() if not str(k).startswith("_")},
                                  sort_keys=True, default=str))
        if time.time() - _recent.get(key, 0.0) < 20:
            voice.say("That is already open.")
            return
        _recent[key] = time.time()
    try:
        result = tools.TOOLS[action]["fn"](args)
    except tools.ToolError as e:
        voice.say(str(e))
        return
    except Exception as e:
        voice.say(f"That did not work: {type(e).__name__}")
        return
    voice.say(result or spoken or "Done.")


def run_tool(action, args, spoken):
    t = tools.TOOLS[action]
    if t["risk"] == "confirm":
        skip = False
        if t["skip"]:
            try:
                skip = bool(t["skip"](args))
            except Exception:
                skip = False
        if not skip:
            try:
                question = t["describe"](args)
            except tools.ToolError as e:
                voice.say(str(e))
                return
            PENDING.clear()
            PENDING.update({"action": action, "args": args, "until": time.time() + 60})
            voice.say(question + " Say yes to confirm, or no to cancel.")
            return
    do_tool(action, args, spoken)


def check_pending(text):
    """True if this sentence answered a pending yes or no question."""
    if not PENDING:
        return False
    if time.time() > PENDING["until"]:
        PENDING.clear()
        return False
    words = re.findall(r"[a-z]+", text.lower())
    action, args = PENDING["action"], PENDING["args"]
    PENDING.clear()
    wordset = set(words)
    if wordset and wordset <= YES_FILLER and (wordset & STRONG_YES or words[:2] == ["do", "it"]):
        do_tool(action, args)
        return True
    if wordset and wordset <= NO_WORDS:
        voice.say("Okay, cancelled.")
        return True
    if wordset & STRONG_YES and not (wordset & {"no", "nope", "cancel", "stop", "don", "not", "never"}):
        PENDING.update({"action": action, "args": args, "until": time.time() + 30})
        voice.say("I only want a clean yes or no for that one. Should I go ahead?")
        return True
    print("  (the pending action was cancelled)")
    return False


def fast_path(text):
    """Short, unambiguous commands run at once, without asking the brain."""
    t = re.sub(r"[^a-z0-9% ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t.split()) > 8 or SLOW.search(t):
        return False
    action, args = None, {}
    if re.search(r"\bbattery\b", t):
        action = "battery"
    elif re.search(r"\b(screenshot|screen shot|green shot|screen grab)\b", t):
        action = "screenshot"
    elif re.search(r"\block\b", t) and re.search(r"\b(screen|laptop|computer)\b", t):
        action = "lock_screen"
    elif re.search(r"\b(volume|sound)\b", t):
        n = find_number(t)
        if n is not None:
            action, args = "set_volume", {"percent": n}
        elif re.search(r"\b(up|increase|raise|louder|higher)\b", t):
            action = "volume_up"
        elif re.search(r"\b(down|decrease|lower|quieter|softer|reduce)\b", t):
            action = "volume_down"
    else:
        m = re.match(r"^(?:please )?(?:open|launch|start)(?: up)? (?:the |my )?(.+?)(?: app| application| folder)?$", t)
        if m:
            name = m.group(1).strip()
            if name in apps.FOLDERS:
                action, args = "open_folder", {"name": name}
            elif apps.find_app(name):
                action, args = "open_app", {"name": name}
    if action is None:
        return False
    print("  [quick command]")
    do_tool(action, args)
    return True


def execute(plan, addressed=False):
    action = str(plan.get("action", "chat"))
    args = plan.get("args")
    if not isinstance(args, dict):
        args = {}
    spoken = str(plan.get("say") or "").strip()
    if action in ("ask", "chat"):
        if spoken:
            voice.say(spoken)
    elif action == "none":
        if addressed:
            voice.say("Sorry, I did not catch that. Could you say it again?")
        else:
            print("  (not for me)")
    elif action in tools.TOOLS:
        run_tool(action, args, spoken)
    else:
        voice.say("I can not do that yet.")


_handle_lock = threading.Lock()


def handle(text, via_wake=True):
    with _handle_lock:
        return _handle(text, via_wake)


def _handle(text, via_wake=True):
    """Returns True when Ana expects an answer from you, so she keeps listening."""
    if check_pending(text):
        return bool(PENDING)
    state.update(activity="thinking", activity_at=time.time())
    try:
        if fast_path(text):
            return False
        t0 = time.time()
        plan = brain.think(text, tools.prompt())
        print(f"  [brain {time.time() - t0:.1f}s]")
        if plan is None:
            voice.say("My thinking service is not answering, so I can only do quick commands right now.")
            return False
        plans = plan.get("actions") if isinstance(plan.get("actions"), list) else [plan]
        plans = [p for p in plans if isinstance(p, dict)][:3]
        plans = dedupe(plans)
        plans.sort(key=lambda p: 1 if tools.TOOLS.get(str(p.get("action")), {}).get("risk") == "confirm" else 0)
        for p in plans:
            execute(p, via_wake)
        return bool(PENDING) or any(str(p.get("action")) == "ask" for p in plans)
    finally:
        if not voice.SPEAKING.is_set():
            state.update(activity="idle", activity_at=time.time())


def greet():
    now = datetime.now()
    part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
    who = config.PET_NAME or "there"
    me = config.ASSISTANT
    line = random.choice([
        f"Good {part}, {who}. {me} reporting for duty.",
        f"Hey {who}. {me} is awake and ready to help.",
        f"Welcome back, {who}. What are we building today?",
    ])
    today = [r for r in reminders.pending() if datetime.fromisoformat(r["due"]).date() == now.date()]
    if today:
        line += f" You have {len(today)} reminder{'s' if len(today) > 1 else ''} today."
    voice.say(line)


def start(watch_reminders=True):
    state.update(paused=False)
    if watch_reminders:
        reminders.watch(reminders.notify)
    companion.start()
    threading.Thread(target=brain.warm, daemon=True).start()
    voice.warm()


def listen():
    greet()
    voice.wait()
    from .ears import Ears
    Ears(handle).run()


def main():
    start()
    if "--text" in sys.argv:
        print("text mode: type a command, Ctrl+C to stop")
        while True:
            try:
                text = input("\nYou: ")
            except (KeyboardInterrupt, EOFError):
                print("\nbye")
                return
            if text.strip():
                handle(text.strip())
                voice.wait()
    listen()


if __name__ == "__main__":
    main()
