"""Jarvis: puts the ears, the brain, the tools and the voice together."""
import atexit
import difflib
import json
import random
import re
import signal
import sys
import threading
import time
from datetime import datetime, timedelta

from ..actions import apps, browser, events, capabilities, clipwatch, coder, files, mail, mpvctl, play, procs, study, tools
from ..brain import brain, companion
from . import config, state
from ..research import topic as research_topic
from ..memory import rag
from ..scheduling import digest, guard, monitor, pomodoro, proactive, reminders
from ..voice import dictate, voice

PENDING = {}
SLOW = re.compile(r"\b(and|then|also|after|before|remind|reminder|draft|email|write|note|find|search|"
                  r"research|create|shut|shutdown|restart|suspend|play|pause|message|send)\b")
MUTE = re.compile(r"(?:please )?mute(?: the| my)?(?: sound| volume| audio| laptop| speakers)?(?: please)?")
UNMUTE = re.compile(r"(?:please )?(?:unmute(?: the| my)?(?: sound| volume| audio| laptop| speakers)?"
                    r"|(?:restore|bring back) (?:the |my )?(?:sound|volume|audio))(?: please)?")
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


NUMW = "|".join(list(UNITS) + list(TENS))
COUNT = rf"(?:\d+|an?|(?:{NUMW})(?: (?:{NUMW}))?)"
UNIT = r"(seconds?|secs?|minutes?|mins?|hours?|hrs?)"


def count(word):
    word = word.lower()
    if word.isdigit():
        return int(word)
    if word in ("a", "an"):
        return 1
    return sum(UNITS.get(w) or TENS.get(w) or 0 for w in word.split())


def seconds(num, unit):
    return count(num) * (1 if unit.lower().startswith("sec") else 3600 if unit.lower().startswith("h") else 60)


def clock(hour, minute, ampm, tomorrow=False):
    """'YYYY-MM-DD HH:MM' for the next time it is hour:minute; None when am or pm is needed and missing."""
    h, mi = int(hour), int(minute or 0)
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.lower() == "pm" else 0)
    elif 0 < h <= 12:
        return None
    if h > 23 or mi > 59:
        return None
    due = datetime.now().replace(hour=h, minute=mi, second=0, microsecond=0)
    if tomorrow or due <= datetime.now():
        due += timedelta(days=1)
    return due.strftime("%Y-%m-%d %H:%M")


def remind_at(m):
    when = clock(m.group(2), m.group(3), m.group(4), bool(m.group(5)))
    return {"task": m.group(1), "when": when} if when else None


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


AGENTS = {
    "coder": ("build_project", "run_project", "fix_last_error", "add_feature", "edit_file", "find_bugs", "explain_file", "git_init_project",
              "install_deps", "apply_edit"),
    "research": ("research", "research_topic", "help_topic", "open_sources"),
    "notes": ("search_docs", "reindex_notes", "take_note", "quick_note", "read_notes", "append_to_note", "summarise_file", "ask_about_file", "search_notes"),
    "study": ("quiz_me", "teach_me", "study_progress", "roadmap_next", "roadmap_done", "log_today", "week_summary"),
}


def agent_of(action):
    if action.startswith("browse") or action in ("new_tab", "close_tab", "confirm_download"):
        return "browser"
    return next((g for g, names in AGENTS.items() if action in names), "")


def do_tool(action, args, spoken=""):
    if action in LAUNCH:
        key = (action, json.dumps({k: v for k, v in args.items() if not str(k).startswith("_")},
                                  sort_keys=True, default=str))
        if time.time() - _recent.get(key, 0.0) < 20:
            voice.say("That one is already open.")
            return
        _recent[key] = time.time()
    group = agent_of(action)
    events.agent_start(group)
    try:
        result = tools.TOOLS[action]["fn"](args)
    except tools.ToolError as e:
        voice.say(str(e))
        return
    except Exception as e:
        print(f"  (tool failed: {type(e).__name__})")
        voice.say("Oops, that did not work. Something broke on my side.")
        return
    finally:
        events.agent_end(group)
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
            voice.say(question + " Say yes or no.")
            return
    do_tool(action, args, spoken)


YES_WORDS = {"yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "proceed"}
NO_START = {"no", "nope", "cancel", "stop", "never", "abort"}
EXTRA_FILLER = YES_WORDS | {"go", "ahead", "do", "it", "please", "sir", "save", "this", "that", "as", "a", "note", "the", "jarvis"}
_last_confirm = [0.0]


def _verdict(words):
    if not words:
        return None
    if words[0] in NO_START or words[:2] in (["don", "t"], ["do", "not"]) or "cancel" in words[:4]:
        return "no"
    head = words[:4]
    if set(head) & YES_WORDS or head[:2] == ["go", "ahead"] or (len(words) <= 6 and "ahead" in words):
        return "yes"
    return None


def check_pending(text):
    """True if this sentence answered a pending yes or no question. The question is used up either way."""
    if not PENDING:
        return False
    if time.time() > PENDING["until"]:
        PENDING.clear()
        return False
    words = re.findall(r"[a-z]+", text.lower())
    verdict = _verdict(words)
    verb = str(PENDING.get("action", "")).split("_")[0]
    if verdict is None and verb and verb in words[:3] and not set(words) - {verb, "it", "this", "that", "window", "the", "please", "now", "do"}:
        verdict = "yes"
    if verdict is None:
        PENDING.clear()
        print("  (the pending action was cancelled)")
        return False
    action, args = PENDING["action"], PENDING["args"]
    PENDING.clear()
    _last_confirm[0] = time.time()
    if verdict == "no":
        browser.forget_downloads()
        voice.say("Okay, cancelled.")
        return True
    do_tool(action, args)
    return True


def _waiting():
    return reminders.active() is not None


DIRECT = [
    (re.compile(r"^(.+)$"), "play_media", lambda m: play.answer(m.group(1)), play.asking),
    (capabilities.ASK, "capabilities", lambda m: {}),
    (capabilities.CAN, "capabilities", lambda m: {"question": m.group(0)}),
    (re.compile(r"^(?:please )?(?:next(?: one| video| song| track)?|another(?: one)?|not this one|something else|play (?:the )?next(?: one| video| song)?)$", re.I),
     "play_next", lambda m: {}, play.active),
    (re.compile(r"^(?:please )?pause(?: it| the (?:video|music|song))?$", re.I), "player_control", lambda m: {"do": "pause"}, mpvctl.running),
    (re.compile(r"^(?:please )?(?:resume|continue|unpause|play)(?: it| the (?:video|music|song))?$", re.I), "player_control", lambda m: {"do": "resume"}, mpvctl.running),
    (re.compile(r"^(?:please )?stop (?:playing|playback|the (?:video|music|song))$", re.I), "player_control", lambda m: {"do": "stop"}, mpvctl.running),
    (re.compile(r"^(?:please )?(?:volume up|louder|turn it up)$", re.I), "player_control", lambda m: {"do": "louder"}, mpvctl.running),
    (re.compile(r"^(?:please )?(?:volume down|quieter|turn it down)$", re.I), "player_control", lambda m: {"do": "quieter"}, mpvctl.running),
    (re.compile(r"^(?:please )?(?:skip|jump|go) (?:forward|ahead)(?: (?:by )?(?:30|thirty) seconds)?$", re.I), "player_control", lambda m: {"do": "forward"}, mpvctl.running),
    (re.compile(r"^(?:please )?(?:go back|rewind|skip back)(?: (?:by )?(?:30|thirty) seconds)?$", re.I), "player_control", lambda m: {"do": "back"}, mpvctl.running),
    (re.compile(r"^(?:please )?play (?!pause\b)(.+)$", re.I), "play_media", lambda m: {"query": m.group(0), "_heard": True}),
    (re.compile(r"^(?:ok|okay|done|got it|thanks|thank you|i did it|noted|i(?:'| )m on it)$", re.I), "ack_reminder", lambda m: {}, _waiting),
    (re.compile(r"^snooze(?: it| this| that)?(?: for)?\s*(.*)$", re.I), "snooze_reminder", lambda m: {"for": m.group(1)}, _waiting),
    (re.compile(r"^remind me again\s*(.*)$", re.I), "snooze_reminder", lambda m: {"until": m.group(1)}, _waiting),
    (re.compile(r"^stop repeating(?: this| that| it)?(?: one)?$", re.I), "stop_repeating", lambda m: {}, _waiting),
    (re.compile(r"^(?:please )?remember that (.+)$", re.I), "remember", lambda m: {"fact": m.group(1)}),
    (re.compile(r"^(?:please )?remember ((?:my|i|i'm|i am|we|our)\b.+)$", re.I), "remember", lambda m: {"fact": m.group(1)}),
    (re.compile(r"^(?:please )?forget (?:about |that |what i said about )?(.+)$", re.I), "forget", lambda m: {"what": m.group(1)}),
    (re.compile(r"^what do you (?:know|remember) about me$", re.I), "what_do_you_know", lambda m: {}),
    (re.compile(r"^in (?:your|my) notes,? (?:can you |could you |please )?(?:update|add|write|put|save) (?:the |that )?(.+)$", re.I),
     "append_to_note", lambda m: {"topic": "jarvis features" if "feature" in m.group(1).lower() else "general",
                                  "text": capabilities.full_list()[:1500] if "feature" in m.group(1).lower() else m.group(1)}),
    (re.compile(r"^(?:please )?(?:update|add to) (?:(?:your|my|the) )?notes?(?: (?:with|about|that|on))?\s*[:,-]?\s*(.+)$", re.I),
     "append_to_note", lambda m: {"topic": "general", "text": m.group(1)}),
    (re.compile(r"^(?:please )?(?:make|take|add|write|save) (?:me )?a note(?: (?:about|on|for) ([\w ]{1,30}?))?\s*[:,-]\s*(.+)$", re.I),
     "take_note", lambda m: {"topic": m.group(1) or "", "text": m.group(2)}),
    (re.compile(r"^what did i (?:note|save)(?: down)?(?: about| on) (.+)$", re.I), "read_notes", lambda m: {"topic": m.group(1)}),
    (re.compile(r"^what did i (?:write|wrote)(?: down)?(?: about| on) (.+)$", re.I), "search_docs", lambda m: {"query": m.group(1)}),
    (re.compile(r"^(?:please )?re-?index (?:my )?(?:notes|documents|files)$", re.I), "reindex_notes", lambda m: {}),
    (re.compile(r"^(?:list|show|read)(?: out)? (?:my )?notes$", re.I), "list_notes", lambda m: {}),
    (re.compile(r"^search (?:my )?(?:notes|documents|pdfs) for (.+)$", re.I), "search_docs", lambda m: {"query": m.group(1)}),
    (re.compile(r"^(?:delete|remove) (?:my )?notes? (?:about|on) (.+)$", re.I), "delete_note", lambda m: {"topic": m.group(1)}),
    (re.compile(r"^what (?:does|did) (?:it|that|the file|the document|the pdf) say about (.+)$", re.I),
     "ask_about_file", lambda m: {"question": m.group(1), "path": ""}),
    (re.compile(r"^read (?:it|that|the file) (?:again|aloud|out loud|out)$", re.I), "read_aloud_file", lambda m: {"path": ""}),
    (re.compile(r"^(?:please )?(?:summari[sz]e|summary of) (it|that|this)$", re.I), "summarise_file", lambda m: {"path": ""}),
    (re.compile(r"^(?:please )?(?:summari[sz]e|summary of) (?!what i copied|my clipboard|the clipboard|this page)(?:the |my )?(.+)$", re.I),
     "summarise_file", lambda m: {"path": m.group(1)}),
    (re.compile(r"^(?:please )?quiz me(?: (?:on|about) (?:the )?(.+))?$", re.I), "quiz_me", lambda m: {"topic": m.group(1) or ""}),
    (re.compile(r"^(?:another|next) question$", re.I), "quiz_me", lambda m: {"topic": study._last["topic"]}, lambda: bool(study._last["topic"])),
    (re.compile(r"^(?:please )?teach me (?:about |how )?(.+)$", re.I), "teach_me", lambda m: {"topic": m.group(1)}),
    (re.compile(r"^(?:what are |what'?s |what s |whats )?my (?:weak|weakest) (?:topics?|areas?|spots?)$|^where am i weak$", re.I), "study_progress", lambda m: {}),
    (re.compile(r"^(?:what'?s|what s|what is|whats) next on my (?:roadmap|plan)$|^what should i (?:study|learn) next$|^next on my roadmap$", re.I), "roadmap_next", lambda m: {}),
    (re.compile(r"^(?:please )?mark (.+?) (?:as )?(?:done|complete|completed|finished)$", re.I), "roadmap_done", lambda m: {"item": m.group(1)}),
    (re.compile(r"^(?:please )?(?:log (?:today|my day)|daily check-?in)(?:[:,]? (.+))?$", re.I), "log_today", lambda m: {"text": m.group(1) or ""}),
    (re.compile(r"^how was my week$|^(?:my )?weekly (?:summary|review)$|^week summary$", re.I), "week_summary", lambda m: {}),
    (re.compile(r"^(?:good morning,? )?(?:give me )?(?:my |the )?(?:morning (?:briefing|digest)|what s my day|what is my day|what'?s my day)$", re.I),
     "morning_briefing", lambda m: {}),
    (re.compile(r"^(?:watch|monitor) (?=.*\b(?:every|changes|for the word)\b)(.+?)(?: every (\d+|an?|one|two|five|ten|fifteen|thirty) ?(minutes?|mins?|hours?|hrs?))?"
                r"(?: (?:and )?(?:tell|let) me when (?:it|that|this) changes)?(?: for the word (\w+))?$", re.I),
     "add_watch", lambda m: {"target": m.group(1), "every": {"a": 1, "an": 1, "one": 1, "two": 2, "five": 5, "ten": 10,
                             "fifteen": 15, "thirty": 30}.get((m.group(2) or "").lower(), m.group(2)),
                             "unit": m.group(3), "word": m.group(4) or ""}),
    (re.compile(r"^(?:list|show) (?:my )?watch(?:es| list)$", re.I), "list_watches", lambda m: {}),
    (re.compile(r"^pause (?:the )?watch (.+)$", re.I), "pause_watch", lambda m: {"watch": m.group(1)}),
    (re.compile(r"^resume (?:the )?watch (.+)$", re.I), "resume_watch", lambda m: {"watch": m.group(1)}),
    (re.compile(r"^(?:remove|stop|delete) (?:the )?watch (.+)$", re.I), "remove_watch", lambda m: {"watch": m.group(1)}),
    (re.compile(r"^(?:please )?(?:check|read|any|show)(?: me)?(?: my| the)? (?:new )?(?:emails?|mail|inbox)(?: please)?$", re.I), "check_email", lambda m: {}),
    (re.compile(r"^(?:please )?check (?:my |the )?spam(?: folder)?$", re.I), "check_spam", lambda m: {}),
    (re.compile(r"^open (?:my )?(?:email|e-mail|gmail|inbox|mail)$", re.I), "open_email", lambda m: {"which": "inbox"}),
    (re.compile(r"^open (that one|the (?:first|second|third|fourth|fifth|sixth) one)$", re.I), "open_email", lambda m: {"which": m.group(1)},
     lambda: bool(mail.SESSION["items"])),
    (re.compile(r"^(that|the (?:first|second|third|fourth|fifth|sixth)) (?:one)?\s*(is not|isn'?t|isn t|'s not|s not|is|'s) important$", re.I),
     "rate_sender", lambda m: {"which": m.group(1), "important": m.group(2) in ("is", "'s")},
     lambda: bool(mail.SESSION["items"])),
    (re.compile(r"^that sender is (not )?important$", re.I), "rate_sender", lambda m: {"which": "that", "important": not m.group(1)},
     lambda: bool(mail.SESSION["items"])),
    (re.compile(r"^(?:please )?(turn on|turn off|enable|disable|start|stop) (?:the |my )?(?:distraction |focus )?guard$", re.I),
     "guard_switch", lambda m: {"on": m.group(1).lower() in ("turn on", "enable", "start")}),
    (re.compile(r"^(?:please )?turn it off$", re.I), "guard_switch", lambda m: {"on": False}, guard.enabled),
    (re.compile(r"^(?:please )?open (?:google chrome|chrome|the browser|a browser|my browser|firefox) (?:and|then) (?:search|google|look up) (?:for )?(.+)$", re.I),
     "browse_search", lambda m: {"query": m.group(1), "site": ""}, lambda: browser.ready()),
    (re.compile(r"^(?:please )?open (?:google chrome|chrome|the browser|a browser|my browser|firefox) (?:and|then) (?:search|google|look up) (?:for )?(.+)$", re.I),
     "web_search", lambda m: {"query": m.group(1)}),
    (re.compile(r"^(?:.*?\b)?open (google|youtube|github|wikipedia) (?:and|then) search (?:for )?(.+)$", re.I), "browse_search",
     lambda m: {"query": m.group(2), "site": m.group(1).lower()}, lambda: browser.ready()),
    (re.compile(r"^(?:.*?\b)?open (google|youtube|github|wikipedia) (?:and|then) search (?:for )?(.+)$", re.I), "web_search",
     lambda m: {"query": m.group(2) + " " + m.group(1)}),
    (re.compile(r"^(?:please )?search (.+?) on (duck ?duck ?go|google|youtube|github)$", re.I), "browse_search",
     lambda m: {"query": m.group(1), "site": m.group(2).lower().replace(" ", "")}, lambda: browser.ready()),
    (re.compile(r"^(?:please )?(?:browser search|search the browser|search in the browser) (?:for )?(.+)$", re.I), "browse_search",
     lambda m: {"query": m.group(1), "site": ""}, lambda: browser.ready()),
    (re.compile(r"^(?:please )?(?:open (?:that|this|the page) in my (?:normal|real|main) browser|open (?:that|this) externally)$", re.I), "browse_external", lambda m: {},
     lambda: browser.active()),
    (re.compile(r"^(?:please )?(?:go to|browse to|browse|visit) ((?:google|youtube|github|wikipedia|stack ?overflow|[a-z0-9-]+(?:\.[a-z0-9-]+)+))$", re.I), "browse_open", lambda m: {"target": m.group(1)}),
    (re.compile(r"^(?:please )?open ([a-z0-9-]+(?:\.[a-z0-9-]+)+)$", re.I), "browse_open", lambda m: {"target": m.group(1)}, lambda: browser.ready()),
    (re.compile(r"^(?:please )?click (?:on )?(.+)$", re.I), "browse_click", lambda m: {"text": m.group(1)}, lambda: browser.active()),
    (re.compile(r"^(?:please )?(?:type|enter) (.+?) (?:into|in) (?:the )?(.+?)(?: box| field)?$", re.I), "browse_type",
     lambda m: {"text": m.group(1), "field": m.group(2)}, lambda: browser.active()),
    (re.compile(r"^(?:please )?scroll (down|up)$", re.I), "browse_scroll", lambda m: {"direction": m.group(1).lower()}, lambda: browser.active()),
    (re.compile(r"^(?:please )?(?:read|summari[sz]e) (?:this|the) (?:page|article|site|website)$", re.I), "browse_read", lambda m: {}, lambda: browser.active()),
    (re.compile(r"^(?:please )?(?:go back|back)$|^browser back$|^go back a page$", re.I), "browse_back", lambda m: {},
     lambda: browser.active() and not mpvctl.running()),
    (re.compile(r"^(?:please )?(?:new|open a new) tab$", re.I), "new_tab", lambda m: {}, lambda: browser.ready()),
    (re.compile(r"^(?:please )?close (?:the |this )?tab$", re.I), "close_tab", lambda m: {}, lambda: browser.active()),
    (re.compile(r"^(?:please )?close (?:the )?browser$", re.I), "close_browser", lambda m: {}, lambda: browser.active()),
    (re.compile(r"^(?:please )?(?:take a )?screenshot of (?:this|the) (?:page|browser|tab)$", re.I), "browse_screenshot", lambda m: {}, lambda: browser.active()),
    (re.compile(r"^(?:please )?close (?:the )?(.+?)(?: app| window)?$", re.I), "close_app", lambda m: {"name": m.group(1)}),
    (re.compile(r"^(?:please )?switch to (?!(?:a |an |the )?(?:male|female|british|english|american) voice)(?!.*\bvoice$)(?:the )?(.+?)(?: app| window)?$", re.I), "switch_app", lambda m: {"name": m.group(1)}),
    (re.compile(r"^(?:please )?minimi[sz]e(?: this| it| the window| this window)?$", re.I), "minimise_window", lambda m: {}),
    (re.compile(r"^(?:please )?(?=.*\bbrightness\b)(.{0,40})$", re.I), "brightness", lambda m: {"text": m.group(1)}),
    (re.compile(r"^(?:please )?open (?:the |my )?(?:file|folder|document|pdf) (.+)$", re.I), "open_path", lambda m: {"name": m.group(1)}),
    (re.compile(r"^(?:please )?open ([a-z0-9-]+(?:\.[a-z]{2,})+)$", re.I), "open_site", lambda m: {"site": m.group(1)}),
    (re.compile(r"^(?:please )?(?:search|google)(?: the web| online)?(?: for)? (?!my\b|notes\b)(.+)$", re.I), "web_search", lambda m: {"query": m.group(1)}),
    (re.compile(rf"^(?:please )?remind me (?:to )?(.+?) in ({COUNT}) {UNIT}$", re.I), "set_reminder",
     lambda m: {"task": m.group(1), "in_seconds": seconds(m.group(2), m.group(3))}),
    (re.compile(rf"^(?:please )?remind me in ({COUNT}) {UNIT} (?:to )?(.+)$", re.I), "set_reminder",
     lambda m: {"task": m.group(3), "in_seconds": seconds(m.group(1), m.group(2))}),
    (re.compile(rf"^(?:please )?remind me to (.+?) every (?:({COUNT}) )?{UNIT}$", re.I), "set_reminder",
     lambda m: {"task": m.group(1), "every_minutes": seconds(m.group(2) or "a", m.group(3)) / 60}),
    (re.compile(r"^(?:please )?remind me to (.+?) (?:at|by) (\d{1,2})(?::(\d{2}))? ?(am|pm)?(?: (tomorrow))?$", re.I),
     "set_reminder", remind_at),
    (re.compile(r"^(?:what are|list|show|read)(?: out)?(?: me)? my (?:pending |upcoming )?reminders$", re.I), "list_reminders", lambda m: {}),
    (re.compile(r"^(?:please )?change (?:your |the )?voice$", re.I), "change_voice", lambda m: {"which": "next"}),
    (re.compile(r"^(?:please )?(?:use|switch to|try) (?:a |an |the )?(male|female|british|english|american) voice$", re.I),
     "change_voice", lambda m: {"which": m.group(1)}),
    (re.compile(r"^(?:please )?(?:use|switch to|try) (?:a |an |the )?([a-z]+) voice$", re.I), "change_voice", lambda m: {"which": m.group(1)}),
    (re.compile(r"^(?:please )?(listen|reply|answer)(?: to me)? in (hindi|kannada|english|auto|automatic|any language|my language)(?: mode)?$", re.I),
     "set_language", lambda m: {"mode": "reply" if m.group(1).lower() != "listen" else "listen", "language": m.group(2)}),
    (re.compile(r"^(?:please )?(?:be )?(chattier|more talkative|quieter)$|^(?:please )?(talk more|talk less)$", re.I), "proactive_level",
     lambda m: {"change": "more" if (m.group(1) or m.group(2)).lower() in ("chattier", "more talkative", "talk more") else "less"}),
    (re.compile(r"^(?:please )?stop talking for (.+)$", re.I), "proactive_quiet", lambda m: {"for": m.group(1)}),
    (re.compile(r"^what voice are you using$|^which voice (?:are you|is this)(?: using)?$", re.I), "what_voice", lambda m: {}),
    (re.compile(r"^(?:please )?open (?:the )?(?:command )?palette$", re.I), "open_palette", lambda m: {}),
    (re.compile(r"^(?:please )?translate (.+?) (?:to|into|in) ([a-z]+)$", re.I), "translate",
     lambda m: {"text": m.group(1), "language": m.group(2)}),
    (re.compile(r"^(?:please )?(?:explain (?:this|the|that) error|explain the error on my clipboard)$", re.I),
     "debug_clipboard", lambda m: {"kind": "error"}),
    (re.compile(r"^(?:please )?(?:debug|fix|find bugs in|check) (?:the |this )?code(?: on my clipboard| i copied)?$", re.I),
     "find_bugs", lambda m: {"file": "clipboard"}),
    (re.compile(r"^(?:please )?(?:find bugs in|debug|fix|check) (?:the |my )?(?:file )?([\w./~-]+\.\w{1,5})$", re.I),
     "find_bugs", lambda m: {"file": m.group(1)}),
    (re.compile(r"^(?:please )?(?:edit|change|modify|update) (?:the )?(?:file )?([\w./~-]+\.\w{1,5}),? (?:to |so that |and )?(.+)$", re.I),
     "edit_file", lambda m: {"file": m.group(1), "change": m.group(2)}),
    (re.compile(r"^(?:please )?add (.+?) to (?:the )?(?:file )?([\w./~-]+\.\w{1,5})$", re.I),
     "edit_file", lambda m: {"file": m.group(2), "change": "add " + m.group(1)}),
    (re.compile(r"^(?:please )?run (?:it|this|the (?:project|program|code|app|file))$", re.I), "run_project", lambda m: {}),
    (re.compile(r"^(?:please )?fix (?:the |that |this )?(?:last )?error$", re.I), "fix_last_error", lambda m: {}),
    (re.compile(r"^(?:please )?add (.+?) to (?:the |my )?([\w -]+?)(?: project| app| site| website)?$", re.I), "add_feature",
     lambda m: {"feature": m.group(1), "project": m.group(2)} if coder.find_project(m.group(2)) else None),
    (re.compile(r"^(?:please )?explain (?:this|the|that) (?:file|code)$", re.I), "explain_file", lambda m: {"file": ""}),
    (re.compile(r"^(?:please )?explain ([\w./~-]+\.\w{1,5})$", re.I), "explain_file", lambda m: {"file": m.group(1)}),
    (re.compile(r"^(?:please )?git init(?:iali[sz]e)?(?: this| the| my)?(?: project)?$|^initiali[sz]e git(?: here| for this project)?$", re.I),
     "git_init_project", lambda m: {"project": ""}),
    (re.compile(r"^(?:please )?(?:build|create|make|write)(?: me)? "
                r"(?!(?:a |an |some )?(?:note|reminder|message|e-?mail|letter|text|essay|paragraph|poem|story|joke|list|summary|draft|call|folder)\b)(?:a |an |some )?(.{6,})$", re.I),
     "build_project", lambda m: {"request": m.group(0)}),
    (re.compile(r"^(?:please )?send (this|it|.+?) to my (phone|mobile|laptop|computer|pc)$", re.I), "send_to_device",
     lambda m: {"what": "" if m.group(1).lower() in ("this", "it") else m.group(1), "device": m.group(2)}),
    (re.compile(r"^(?:please )?(turn on|turn off|enable|disable) (?:the |my )?clipboard (?:monitor|watcher|watch)$", re.I),
     "clip_monitor_switch", lambda m: {"on": m.group(1).lower() in ("turn on", "enable")}),
    (re.compile(r"^(?:please )?(?:research|find out about) (?!.*\b(?:hackathons?|events?|news)\b)(.+)$", re.I), "research_topic",
     lambda m: {"topic": m.group(1)}),
    (re.compile(r"^(?:show me(?: the sources)?|open (?:the )?sources|show me the links)$", re.I), "open_sources", lambda m: {},
     lambda: research_topic.has_sources()),
    (re.compile(r"^(?:i need help with|help me with|help me understand) (.+)$", re.I), "help_topic", lambda m: {"topic": m.group(1)}),
    (re.compile(r"^(how (?:do|can|should) (?:i|we) .+)$", re.I), "help_topic", lambda m: {"topic": m.group(1)}),
    (re.compile(r"^(?:please )?start (?:a )?focus(?: timer| session)?(?: (?:for )?(\d{1,3}|(?:" + NUMW + r")(?: (?:" + NUMW + r"))?)(?: minutes?| mins?)?)?$", re.I), "start_focus",
     lambda m: {"minutes": (find_number(m.group(1).lower()) or "") if m.group(1) else ""}),
    (re.compile(r"^(?:please )?(?:(?:take|start) a )?break(?: (?:for )?(\d{1,2}|(?:" + NUMW + r")(?: (?:" + NUMW + r"))?)(?: minutes?| mins?)?)?$", re.I), "start_break",
     lambda m: {"minutes": (find_number(m.group(1).lower()) or "") if m.group(1) else ""}),
    (re.compile(r"^(?:please )?(?:stop|end|cancel) (?:the )?(?:focus|pomodoro|timer|focus timer|break)$", re.I), "stop_focus", lambda m: {}),
    (re.compile(r"^how (?:long|much time) (?:is )?left$|^time left$", re.I), "focus_left", lambda m: {}, pomodoro.status),
    (re.compile(r"^(?:please )?(?:change|set|switch) (?:the |my )?(?:dashboard )?(?:theme|colou?rs?) to ([a-z ]+)$", re.I), "change_theme", lambda m: {"theme": m.group(1)}),
    (re.compile(r"^(?:please )?(next|random) (?:theme|colou?r)$", re.I), "change_theme", lambda m: {"theme": m.group(1)}),
    (re.compile(r"^(?:show (?:me )?)?(?:jarvis )?stats$|^jarvis stats$", re.I), "jarvis_stats", lambda m: {}),
    (re.compile(r"^good morning(?:,? jarvis)?$", re.I), "good_morning", lambda m: {}),
    (re.compile(r"^note\s*[:,-]\s*(.+)$", re.I), "quick_note", lambda m: {"text": m.group(1)}),
    (re.compile(r"^(?:end|stop|turn off) focus mode$", re.I), "focus_mode", lambda m: {"end": True}),
    (re.compile(r"^(?:start |turn on )?focus mode(?: for (.+))?$", re.I), "focus_mode", lambda m: {"for": m.group(1) or ""}),
    (re.compile(r"^i(?:'m| m| am) on a break$", re.I), "take_break", lambda m: {}),
    (re.compile(r"^leave me alone(?: for (.+))?$", re.I), "take_break", lambda m: {"for": m.group(1) or ""}),
    (re.compile(r"^(?:what s|what is|whats|what'?s) my screen time$|^how did i spend my time(?: today)?$", re.I), "screen_time", lambda m: {}),
    (re.compile(r"^what did we (?:talk|speak|chat|discuss)(?: about)?\s*(.*)$", re.I), "recall_day", lambda m: {"when": m.group(1)}),
    (re.compile(r"^(?:please )?(?:watch|show me)(?: a| an| the)? (?:video|videos) (?:of|on|about|for) (.+)$", re.I), "play_media",
     lambda m: {"query": "play a video on " + m.group(1), "_heard": True}),
    (re.compile(r"^(?:please )?watch (?!the (?:sources|links)\b|my\b|this\b|that\b|it\b|out\b|for\b|every\b)(.+)$", re.I), "play_media",
     lambda m: {"query": "play a video of " + m.group(1), "_heard": True}),
    (re.compile(r"^(?:please )?show me (?!(?:the |my |all |some |any |me |what |how |where |when |why |which |a list|that|this|it\b|reminders?\b|notes?\b|e-?mails?\b|mail\b|files?\b|screen\b|unread\b|clipboard\b))(.+)$", re.I), "play_media",
     lambda m: {"query": "play a video of " + m.group(1), "_heard": True}),
]


LOCAL_PHRASES = {
    "be chattier": ("proactive_level", {"change": "more"}), "talk more": ("proactive_level", {"change": "more"}),
    "be more talkative": ("proactive_level", {"change": "more"}),
    "dont be chatty": ("proactive_level", {"change": "less"}), "be quiet": ("proactive_level", {"change": "less"}),
    "be quieter": ("proactive_level", {"change": "less"}), "talk less": ("proactive_level", {"change": "less"}),
    "change your voice": ("change_voice", {"which": "next"}),
    "what voices do you have": ("list_voices", {}), "which voices do you have": ("list_voices", {}),
    "list the voices": ("list_voices", {}),
}
LANGUAGES = ("hindi", "kannada", "english", "auto")
STOP = re.compile(r"^(?:please )?(?:stop(?: talking| speaking| it)?|quiet|enough|shut up|bas|ruko|रुको|रुक|चुप(?: रहो| हो जाओ)?)$")
STOP_MUSIC = re.compile(r"^(?:please )?(?:stop(?: it| the (?:music|song|video|player))?|stop music|stop playing|"
                        r"quiet|enough|shut up|bas|ruko|रुको|रुक|चुप(?: रहो| हो जाओ)?)$")
PAUSE_MUSIC = re.compile(r"^(?:please )?pause(?: it| the (?:music|song|video|player)| music)?$")


def close(word, options, cutoff=0.75):
    got = difflib.get_close_matches(word, list(options), 1, cutoff)
    return got[0] if got else None


def fuzzy(text):
    """Control phrases that survive small mishearings, matched here without the brain."""
    words = [w for w in re.sub(r"[^a-z ]", "", text.lower().replace("'", "")).split() if w != "please"]
    plain = " ".join(words)
    action = args = None
    hit = close(plain, LOCAL_PHRASES, 0.82)
    if hit:
        action, args = LOCAL_PHRASES[hit]
    elif len(words) >= 4 and close(" ".join(words[:2]), ["stop talking"], 0.8) and words[2] == "for":
        action, args = "proactive_quiet", {"for": " ".join(words[3:])}
    elif len(words) == 3 and words[1] == "in" and close(words[0], ["listen"], 0.8) and close(words[2], LANGUAGES, 0.7):
        action, args = "set_language", {"mode": "listen", "language": close(words[2], LANGUAGES, 0.7)}
    elif len(words) >= 3 and words[0] in ("use", "switch", "try") and words[-2] not in ("a", "an", "the") \
            and close(words[-1], ["voice"], 0.8):
        action, args = "change_voice", {"which": words[-2]}
    if action not in tools.TOOLS:
        return False
    print("  [direct command]")
    run_tool(action, args, "")
    return True


def direct(text):
    """Phrases that map straight to one tool, without asking the brain."""
    t = " ".join(text.strip().rstrip(".?!,").split())
    t = re.sub(r"^(?:(?:so|well|okay|ok|now|and|then|alright|hey)\b[ ,]*)+", "", t, flags=re.I) or t
    for pattern, action, make, *guard in DIRECT:
        m = pattern.match(t)
        if m and action in tools.TOOLS and (not guard or guard[0]()):
            args = make(m)
            if args is None:
                continue
            print("  [direct command]")
            events.emit("route", "direct " + action)
            run_tool(action, args, "")
            return True
    return fuzzy(t)


def fast_path(text):
    """Short, unambiguous commands run at once, without asking the brain."""
    t = re.sub(r"[^a-z0-9% ]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    if not t or len(t.split()) > 8 or SLOW.search(t):
        return False
    action, args = None, {}
    if re.fullmatch(r"(?:what s |what is |tell me )?(?:the )?(?:current )?time(?: is it)?(?: now| please)?|what time is it(?: now)?", t):
        action, args = "time_date", {"what": "time"}
    elif re.fullmatch(r"(?:what s |what is |tell me )?(?:the |today s )?(?:current )?date(?: today)?|what day is it(?: today)?|what is today s date", t):
        action, args = "time_date", {"what": "date"}
    elif re.search(r"\bbattery\b", t):
        action = "battery"
    elif re.search(r"\b(system status|how s my (system|laptop|computer)|how is my (system|laptop|computer))\b", t):
        action = "system_status"
    elif re.search(r"\b(screenshot|screen shot|green shot|screen grab)\b", t):
        action = "screenshot"
    elif re.search(r"\bclipboard\b", t):
        action = "read_clipboard"
    elif re.search(r"\b(read|what s on|what is on|whats on) (my |the )?screen\b", t):
        action = "read_screen"
    elif re.search(r"\b(on|read|describe|at|see) (my |the )?screen\b", t):
        action = "describe_screen"
    elif re.search(r"\block\b", t) and re.search(r"\b(screen|laptop|computer)\b", t):
        action = "lock_screen"
    elif UNMUTE.fullmatch(t):
        action = "unmute"
    elif MUTE.fullmatch(t):
        action = "mute"
    elif re.search(r"\b(volume|sound)\b", t):
        n = find_number(t)
        by = {"by": n} if n else {}
        if re.search(r"\b(up|increase|raise|louder|higher)\b", t):
            action, args = "volume_up", by
        elif re.search(r"\b(down|decrease|lower|quieter|softer|reduce)\b", t):
            action, args = "volume_down", by
        elif n is not None:
            action, args = "set_volume", {"percent": n}
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
    events.emit("route", "quick " + action)
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
            voice.say("Sorry, I missed that. Could you say it once more?")
        else:
            print("  (not for me)")
    elif action in tools.TOOLS:
        run_tool(action, args, spoken)
    else:
        voice.say("I cannot do that one yet, sorry.")


_handle_lock = threading.Lock()


def collapse_repeats(text):
    """'Stop playing. Stop playing' and 'next next' become one phrase, so the direct command path still matches."""
    parts = [p.strip() for p in re.split(r"(?<=[.!?,;])\s+", text.strip()) if p.strip()]
    key = [re.sub(r"[^\w\s]", "", p.lower()).strip() for p in parts]
    if len(parts) > 1 and len(set(key)) == 1 and key[0]:
        return parts[0].rstrip(".!?,; ")
    words = text.split()
    plain = [re.sub(r"[^\w']", "", w.lower()) for w in words]
    for size in range(1, min(4, len(words) // 2) + 1):
        if len(words) % size == 0 and plain[:size] * (len(words) // size) == plain and all(plain[:size]):
            return " ".join(words[:size]).rstrip(".!?,; ")
    return text


def handle(text, via_wake=True):
    with _handle_lock:
        return _handle(text, via_wake)


APP_STOP = re.compile(r"^(?:please )?(?:(?:stop|kill|close) (?:the (?:app|server|project|website|site))|stop running)$")
APP_STOP_IT = re.compile(r"^(?:please )?(?:stop|kill) it$")


def stop_media(plain):
    """Stop or pause mpv for a stop word, whenever it is running. Returns True if the player was touched."""
    pause = bool(PAUSE_MUSIC.match(plain)) or plain in ("quiet", "please quiet")
    if not (pause or STOP_MUSIC.match(plain)) or not mpvctl.running():
        return False
    if pause:
        if mpvctl.playing():
            mpvctl.pause(True)
    else:
        mpvctl.stop()
    return True


def _handle(text, via_wake=True):
    """Returns True when Jarvis expects an answer from you, so it keeps listening."""
    text = collapse_repeats(text)
    plain = re.sub(r"[!-/:-@\[-`{-~।]", "", text.lower()).strip()
    spoke = voice.SPEAKING.is_set()
    if procs.alive() and (APP_STOP.match(plain) or (APP_STOP_IT.match(plain) and not spoke)):
        do_tool("stop_project", {})
        return False
    if stop_media(plain):
        if spoke:
            voice.stop()
        PENDING.clear()
        state.update(touched_at=time.time())
        return False
    if STOP.match(plain) and (spoke or not PENDING):
        voice.stop()
        PENDING.clear()
        study.cancel()
        return False
    if check_pending(text):
        return bool(PENDING)
    reply = study.take(text)
    if reply is not None:
        voice.say(reply)
        return study.waiting()
    spec = coder.take_spec(text)
    if spec:
        run_tool("build_project", {"request": "build me " + spec}, "")
        return False
    if time.time() - _last_confirm[0] < 20 and _verdict(re.findall(r"[a-z]+", text.lower())) == "yes" \
            and not set(re.findall(r"[a-z]+", text.lower())) - EXTRA_FILLER:
        return False
    choice = files.take_choice(text)
    if choice:
        run_tool(choice[0], choice[1], "")
        return bool(PENDING) or files.waiting()
    held = files.hold_choice(text)
    if held:
        voice.say(held)
        return True
    state.update(activity="thinking", activity_at=time.time(), touched_at=time.time())
    try:
        if direct(text):
            return bool(PENDING) or files.waiting() or play.asking() or study.waiting() or coder.asking()
        if fast_path(text):
            return False
        t0 = time.time()
        names = tools.pick_tools(text)
        events.emit("route", "brain " + (",".join(names) if names else "chat"))
        plan = brain.think(text, tools.prompt(names), names) if names else brain.chat(text)
        print(f"  [brain {time.time() - t0:.1f}s ~{brain.take_tokens()} tokens]")
        if plan is None:
            voice.say("I cannot reach my brain right now, so only quick things like time, volume and reminders will work.")
            return False
        plans = plan.get("actions") if isinstance(plan.get("actions"), list) else [plan]
        plans = [p for p in plans if isinstance(p, dict)][:3]
        plans = dedupe(plans)
        plans.sort(key=lambda p: 1 if tools.TOOLS.get(str(p.get("action")), {}).get("risk") == "confirm" else 0)
        for p in plans:
            execute(p, via_wake)
        return bool(PENDING) or files.waiting() or any(str(p.get("action")) == "ask" for p in plans)
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


def _on_signal(signum, frame):
    sys.exit(0)


def start(watch_reminders=True):
    state.update(paused=False)
    atexit.register(brain.finish)
    atexit.register(mpvctl.stop)
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _on_signal)
    if watch_reminders:
        reminders.watch(reminders.notify)
        digest.watch(lambda text: voice.say(voice.Full(text)))
        monitor.watch()
    rag.start()
    pomodoro.resume()
    dictate.start(voice.say)
    companion.start()
    proactive.start()
    if guard.enabled():
        guard.start()
    clipwatch.start()
    threading.Thread(target=command_loop, daemon=True).start()
    threading.Thread(target=brain.warm, daemon=True).start()
    voice.warm()


def check_stop_key(seen):
    """Kill mpv when the STOP button, Ctrl+. or voice --stop set a newer stop_at. Returns the newest stop_at seen."""
    at = float(state.read()["stop_at"] or 0)
    if at > seen:
        mpvctl.stop()
        return at
    return seen


def command_loop():
    """Runs commands typed into the palette, which sends them through the shared state file."""
    last = 0.0
    stopped = float(state.get("stop_at") or 0)
    while True:
        time.sleep(0.5)
        st = state.read()
        stopped = check_stop_key(stopped)
        if st["command"] and st["command_at"] > last:
            last, text = st["command_at"], st["command"]
            state.update(command="")
            try:
                handle(text)
            except Exception as e:
                print(f"  (palette command failed: {type(e).__name__})")


def listen():
    greet()
    voice.wait()
    from ..voice.ears import Ears
    Ears(handle).run()


def main():
    if "--text" not in sys.argv and "--no-ui" not in sys.argv:
        from ..ui import dashboard
        return dashboard.run()
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
