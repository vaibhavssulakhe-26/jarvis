"""Voice control for the listening mode."""
from ..voice import listen
from .tools import tool


@tool("crowd_mode", 'args {"on": true or false} - crowd mode: the wake word is needed for every command; for "crowd mode on", "crowd mode off"')
def crowd_mode(args):
    on = args.get("on")
    on = on if isinstance(on, bool) else str(on).lower() in ("1", "true", "yes", "on")
    listen.set_crowd(on)
    return "Crowd mode is on. I will only answer after my name." if on else "Crowd mode is off."
