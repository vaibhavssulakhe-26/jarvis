"""What Jarvis can do, read from the tool registry so the answer never drifts from the code."""
import re

from ..voice import voice
from . import events
from .tools import TOOLS, tool

CATEGORIES = [
    ("Time and system", "time_date battery system_status lock_screen suspend shutdown restart brightness"),
    ("Volume", "set_volume volume_up volume_down mute unmute"),
    ("Reminders", "set_reminder cancel_reminder list_reminders clear_reminders ack_reminder snooze_reminder move_reminder stop_repeating"),
    ("Apps and windows", "open_app open_folder open_path open_site close_app switch_app minimise_window open_palette"),
    ("Music and video", "play_media play_next player_control media"),
    ("Screen and clipboard", "screenshot describe_screen read_screen read_clipboard clip_summary clip_monitor_switch translate"),
    ("Web and research", "web_search research research_topic open_sources open_url help_topic add_watch list_watches pause_watch resume_watch remove_watch"),
    ("Browser", "browse_open browse_search browse_click browse_type browse_scroll browse_read browse_back new_tab close_tab close_browser browse_screenshot"),
    ("Notes and memory", "take_note read_notes list_notes search_notes search_docs reindex_notes append_to_note delete_note draft_text remember forget what_do_you_know recall_day"),
    ("Email and messages", "check_email check_spam open_email rate_sender message_contact send_screenshot send_to_device"),
    ("Files", "find_file summarise_file ask_about_file read_aloud_file"),
    ("Coding", "build_project edit_file apply_edit find_bugs run_project stop_project fix_last_error add_feature explain_file git_init_project install_deps debug_clipboard"),
    ("Study", "quiz_me teach_me study_progress roadmap_next roadmap_done log_today week_summary"),
    ("Focus", "start_focus start_break stop_focus focus_left quick_note good_morning guard_switch focus_mode take_break screen_time morning_briefing"),
    ("Voice and chat", "change_theme jarvis_stats list_voices change_voice what_voice set_language proactive_level proactive_quiet"),
]
ASK = re.compile(r"^(?:hey |ok |okay |so )?(?:please )?(?:help|what can you do(?: now| for me)?|what do you do|what are you able to do|"
                 r"what are your (?:new |latest |current )?(?:features|abilities|skills|capabilities)|tell me (?:about )?your (?:new |latest )?(?:features|abilities|skills)|"
                 r"what(?:'s| is) new(?: with you)?|what can i (?:ask|say to) you|what are you capable of|how can you help(?: me)?|"
                 r"list (?:your )?(?:new )?(?:features|commands)|show (?:me )?your (?:new )?features|your (?:new )?features)\??$", re.I)
CAN = re.compile(r"^(?:hey |ok |okay |so )?(?:please )?(?:can|could|are) you (?:also |even |really )?(?:able to )?"
                 r"(build|code|program|write code|write programs|run code|run programs|create (?:an? )?(?:app|apps|program|website|project)|make (?:an? )?(?:app|apps|program|website)|"
                 r"browse|surf|search the web|use (?:a|the) browser|open websites|control (?:a|the) browser)\b.*$", re.I)
TOPICS = {
    "code": ("build_project run_project stop_project fix_last_error add_feature explain_file git_init_project find_bugs edit_file", "write, run and fix code"),
    "browse": ("browse_open browse_search browse_click browse_scroll browse_read browse_back new_tab close_tab", "browse the web"),
}


def groups():
    """(category, [tool names]) for the tools that are registered, with anything unlisted under Other."""
    seen, out = set(), []
    for title, names in CATEGORIES:
        have = [n for n in names.split() if n in TOOLS]
        seen.update(have)
        if have:
            out.append((title, have))
    rest = [n for n in TOOLS if n not in seen]
    if rest:
        out.append(("Other", rest))
    return out


def answer_can(question):
    """A yes or no from the tool registry, never a guess: it names what is actually installed."""
    t = str(question).lower()
    kind = "browse" if re.search(r"browse|surf|web|website|browser", t) else "code"
    names, verb = TOPICS[kind]
    have = [n.replace("_", " ") for n in names.split() if n in TOOLS]
    if not have:
        return f"Not on this setup yet. The {kind} tools are not installed."
    return f"Yes, I can {verb}. For example: " + ", ".join(have[:6]) + ". The full list is on your screen."


def summary():
    return ("I can help with " + ", ".join(t.lower() for t, _ in groups()[:8]) + ", and more. "
            "The full list is on your screen. Ask me for any of them by name.")


def full_list():
    lines = []
    for title, names in groups():
        lines.append(title + ": " + ", ".join(n.replace("_", " ") for n in names))
    return "\n".join(lines)


@tool("capabilities", 'args {"question": "optional"} - say what Jarvis can do; for "what can you do", "what are your features", "help"')
def capabilities(args):
    q = str(args.get("question") or "")
    if CAN.match(q):
        return answer_can(q)
    text = "What I can do:\n" + full_list()
    print(text)
    events.emit("jarvis", text)
    return summary()
