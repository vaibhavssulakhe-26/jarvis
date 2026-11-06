"""Morning briefing on request."""
from ..scheduling import digest
from .tools import tool


@tool("morning_briefing", 'args {} - the morning briefing: date, weather, reminders, notes, mail and headlines; for "morning briefing", "what\'s my day"')
def morning_briefing(args):
    return digest.build()
