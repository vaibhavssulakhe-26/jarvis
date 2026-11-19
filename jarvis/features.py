"""One registry of everything Jarvis can open or do: sections, settings and tools. The command palette searches it and About JARVIS will list it.
No Qt here. An entry has an action that says where Enter goes; an entry that is planned but not built is kept and marked unavailable, with the reason."""
import difflib
import re
from dataclasses import dataclass, field

from .core import config

SECTION, SETTING, TOOL = "section", "setting", "tool"
GROUP_ORDER = {SECTION: 0, SETTING: 1, TOOL: 2}
STOP = {"the", "a", "an", "my", "to", "of", "please", "open", "go", "show", "me", "jarvis", "i", "want", "can", "you", "for", "and", "it", "on", "in"}
MIN_SCORE = 0.38

# page names are the ones the new window knows; "globe" and "bubbles" are the two halves of the first screen
SECTIONS = (
    ("Home", "home globe start main screen back", ("globe",)),
    ("Settings", "settings preferences options configuration theme keys diagnostics", ("page", "Settings")),
    ("Notes", "notes documents files knowledge memory graph search notes", ("page", "Notes")),
    ("Chat", "chat conversation talk messages thread type", ("page", "Chat")),
    ("Web Search", "web search browser internet google site agent", ("page", "Web")),
    ("Media", "media music video player play songs now playing", ("page", "Media")),
    ("Stats", "stats statistics usage tokens providers numbers", ("page", "Stats")),
    ("Activity", "activity log events what happened failures routing", ("page", "Activity")),
    ("Code", "code coder build projects programming files generated", ("page", "Code")),
)
GATED = (
    ("Study", "study quiz learning roadmap streak revision", ("page", "Study"), "STUDY"),
    ("Jobs", "jobs applications interview tracker recruiter career", ("page", "Jobs"), "JOBS"),
)
def _settings_page(section):
    return ("page", "Settings", section)


SETTINGS = (
    ("General settings", "general settings options keys diagnostics doctor crowd mode mute", _settings_page("general")),
    ("Profile", "profile name full name preferred name nickname preferences about me who am i", _settings_page("profile")),
    ("Nickname", "nickname call me pet name what to call me", _settings_page("profile")),
    ("Preferences", "preferences how i like answers short metric", _settings_page("profile")),
    ("Memory manager", "memory memories remembered facts list search edit delete clear forget manage", _settings_page("memory")),
    ("Pause remembering", "pause remembering stop remembering memory off", _settings_page("memory")),
    ("What may be remembered", "memory categories sensitive health people allow remember switches", _settings_page("memory")),
    ("Customization", "customization customise customize appearance look personalise", _settings_page("customize")),
    ("Accent colour", "accent colour color highlight hue personalise theme", _settings_page("customize")),
    ("Background", "background wallpaper backdrop colour dark", _settings_page("customize")),
    ("Theme and colours", "theme colour color hue appearance look dark", _settings_page("customize")),
    ("Globe look", "globe look dots size glow density sphere", _settings_page("customize")),
    ("Animation intensity", "animation intensity motion particles speed calm", _settings_page("customize")),
    ("Chat appearance", "chat appearance text size font spacing bubbles", _settings_page("customize")),
    ("Reply language", "reply language english hindi kannada speak talk answer respond switch", _settings_page("customize")),
    ("Assistant personality", "personality tone style friendly formal playful concise coach", _settings_page("customize")),
    ("Voice settings", "voice settings speed speaking rate pitch speaker test", _settings_page("customize")),
    ("Models and providers", "models providers brains ollama groq openrouter fallback primary usage errors", _settings_page("models")),
    ("API keys", "api keys key env where groq openrouter token", _settings_page("models")),
    ("OpenRouter model", "openrouter model picker list choose", _settings_page("models")),
    ("Crowd mode", "crowd noise wake word listening noisy room", _settings_page("general")),
    ("Mute Jarvis's voice", "mute silence quiet voice speaker volume off", _settings_page("general")),
    ("Low power mode", "low power battery saver slow fps animation", ("toggle", "low_power")),
    ("Reduced motion", "reduce motion animation accessibility calm still particles", ("toggle", "reduced_motion")),
    ("Toggle full screen", "fullscreen full screen window maximise", ("window", "fullscreen")),
)
PLANNED = (
    ("About JARVIS", "about version features list what is", "arrives in a later update"),
)
TITLES = {
    "change_voice": "Change assistant voice", "list_voices": "List available voices", "what_voice": "Which voice is in use",
    "forget": "Delete memory", "show_memory": "Show memory", "recall_memory": "Search memory", "remember": "Remember something",
    "change_theme": "Change theme", "run_diagnostics": "Run diagnostics", "set_reminder": "Set a reminder",
    "list_reminders": "List reminders", "cancel_reminder": "Cancel a reminder", "mute": "Mute", "unmute": "Unmute",
    "set_volume": "Set volume", "system_status": "System status", "which_model": "Which model is in use",
    "web_search": "Search the web", "play_media": "Play music or video", "crowd_mode": "Crowd mode on or off",
    "start_focus": "Start a focus session", "take_note": "Take a note", "quick_note": "Quick note", "read_screen": "Read my screen",
    "describe_screen": "Describe my screen", "translate": "Translate", "check_email": "Check email", "jarvis_stats": "Jarvis statistics",
}
EXTRA_WORDS = {
    "forget": "delete erase remove clear memory facts remembered",
    "change_voice": "voice speaker tts speech piper switch pick select assistant",
    "change_theme": "colour color appearance look",
    "show_memory": "what do you remember memory facts",
    "mute": "silence quiet", "set_volume": "sound loudness",
}
STARTERS = {"change_voice": "use the next voice", "forget": "forget ", "list_voices": "what voices do you have", "what_voice": "what voice are you using",
            "change_theme": "next theme", "run_diagnostics": "run diagnostics", "show_memory": "what do you remember", "system_status": "how's my system",
            "mute": "mute", "unmute": "unmute", "capabilities": "what can you do", "which_model": "which model are you using",
            "jarvis_stats": "jarvis stats", "read_screen": "read my screen", "good_morning": "good morning", "time_date": "what time is it"}


@dataclass
class Feature:
    id: str
    title: str
    keywords: str
    group: str
    action: tuple
    available: bool = True
    why: str = ""
    words: dict = field(default_factory=dict, repr=False)

    def tokens(self):
        if not self.words:
            self.words = {"title": _words(self.title), "keys": _words(self.keywords)}
        return self.words


def _stem(w):
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _words(text):
    return [_stem(w) for w in re.findall(r"[a-z0-9]+", str(text).lower())]


def humanize(name):
    return name.replace("_", " ").capitalize()


def build():
    """The registry as it is right now: gated sections follow their flags, tools come from the live tool table."""
    from .actions import tools
    items = []
    for title, words, action in SECTIONS:
        items.append(Feature("section:" + title.lower().replace(" ", "-"), title, words, SECTION, action))
    for title, words, action, flag in GATED:
        on = config.flag(flag, False)
        items.append(Feature("section:" + title.lower(), title, words, SECTION, action, on, "" if on else f"turn on with {flag}=on"))
    for title, words, action in SETTINGS:
        items.append(Feature("setting:" + title.lower().replace(" ", "-"), title, words, SETTING, action))
    for title, words, why in PLANNED:
        items.append(Feature("planned:" + title.lower().replace(" ", "-"), title, words, SETTING, ("unavailable",), False, why))
    for name in sorted(tools.TOOLS):
        doc = tools.TOOLS[name]["doc"]
        desc = doc.split(" - ", 1)[-1] if " - " in doc else doc
        words = f"{name.replace('_', ' ')} {desc} {EXTRA_WORDS.get(name, '')}"
        items.append(Feature("tool:" + name, TITLES.get(name, humanize(name)), words, TOOL, ("tool", name, STARTERS.get(name, humanize(name).lower() + " "))))
    return items


_registry = []


def all_features(refresh=False):
    if refresh or not _registry:
        _registry[:] = build()
    return list(_registry)


def _match(q, tokens):
    """How well one query word matches a list of words: 1 exact, 0.8 prefix, 0.5 inside, a scaled spelling ratio for near misses."""
    best = 0.0
    for t in tokens:
        if q == t:
            return 1.0
        if len(q) >= 2 and t.startswith(q):
            best = max(best, 0.8)
        elif len(q) >= 3 and q in t:
            best = max(best, 0.5)
        elif len(q) >= 4 and len(t) >= 4:
            r = difflib.SequenceMatcher(None, q, t).ratio()
            if r >= 0.78:
                best = max(best, r * 0.65)
    return best


def score(query_words, f):
    if not query_words:
        return 0.0
    tok = f.tokens()
    total = 0.0
    for q in query_words:
        total += max(_match(q, tok["title"]) * 1.0, _match(q, tok["keys"]) * 0.7)
    s = total / len(query_words)
    if query_words == tok["title"]:
        s += 1.0
    elif tok["title"][:len(query_words)] == query_words:
        s += 0.4
    return s


def search(query, limit=8, features=None):
    """Features that match the query, best first. An empty query lists the sections. Unavailable entries rank below an equal available one."""
    feats = features if features is not None else all_features()
    words = [w for w in _words(query) if w not in STOP]
    if not words:
        shown = [f for f in feats if f.group == SECTION]
        return shown[:limit]
    scored = []
    for f in feats:
        s = score(words, f)
        if s >= MIN_SCORE:
            scored.append((-(s - (0.05 if not f.available else 0)), GROUP_ORDER[f.group], f.title.lower(), f))
    scored.sort(key=lambda x: x[:3])
    return [x[3] for x in scored[:limit]]
