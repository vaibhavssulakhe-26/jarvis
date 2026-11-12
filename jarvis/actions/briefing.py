"""Morning briefing on request: the saved briefing from data/briefings, built now if there is none from the last three hours."""
import time

from ..scheduling import digest
from ..voice import speech
from . import events
from .tools import tool

FRESH_SECONDS = 3 * 3600


def show(fresh=False):
    """Print the full briefing, send it to the dashboard, and return up to three sentences to speak."""
    from ..routines import morning
    got = morning.latest()
    if fresh or got is None or time.time() - got["path"].stat().st_mtime > FRESH_SECONDS:
        try:
            result = morning.build()
        except Exception:
            return digest.build()
        got = {"text": result["text"], "spoken": result["spoken"]}
    print("\n" + got["text"] + "\n")
    events.emit("sys", got["text"])
    return speech.Full(got["spoken"])


@tool("morning_briefing", 'args {} - the morning briefing: unread mail, calendar, reminders, roadmap and focus; for "morning briefing", "what\'s my day"')
def morning_briefing(args):
    return show()
