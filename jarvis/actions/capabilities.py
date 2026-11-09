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
    ("Screen and clipboard", "screenshot describe_screen read_clipboard clip_summary clip_monitor_switch translate"),
    ("Web and research", "web_search research research_topic open_sources open_url help_topic add_watch list_watches pause_watch resume_watch remove_watch"),
    ("Notes and memory", "take_note read_notes list_notes search_notes append_to_note delete_note draft_text remember forget what_do_you_know recall_day"),
    ("Email and messages", "check_email check_spam open_email rate_sender message_contact send_screenshot send_to_device"),
    ("Files", "find_file summarise_file ask_about_file read_aloud_file"),
    ("Coding", "build_project edit_file apply_edit find_bugs run_project debug_clipboard"),
    ("Focus", "guard_switch focus_mode take_break screen_time morning_briefing"),
    ("Voice and chat", "list_voices change_voice what_voice set_language proactive_level proactive_quiet"),
]
ASK = re.compile(r"^(?:please )?(?:help|what can you do|what do you do|what are your (?:features|abilities|skills)|what are you able to do|"
                 r"what can i (?:ask|say to) you|what are you capable of|how can you help(?: me)?|list (?:your )?(?:features|commands))$", re.I)


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


def summary():
    return ("I can help with " + ", ".join(t.lower() for t, _ in groups()[:8]) + ", and more. "
            "The full list is on your screen. Ask me for any of them by name.")


def full_list():
    lines = []
    for title, names in groups():
        lines.append(title + ": " + ", ".join(n.replace("_", " ") for n in names))
    return "\n".join(lines)


@tool("capabilities", 'args {} - say what Jarvis can do; for "what can you do", "what are your features", "help"')
def capabilities(args):
    text = "What I can do:\n" + full_list()
    print(text)
    events.emit("jarvis", text)
    return summary()
