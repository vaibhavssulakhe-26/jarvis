"""Voice tools for the holo viewer. All the work is in jarvis/holo.py."""
from .. import holo
from .tools import tool


@tool("open_holo", 'args {} - open the hologram viewer (starts handctl\'s holo mode); for "open holo"')
def open_holo(args):
    holo.start() if not holo.running() else holo.call("open")
    return "The hologram is open."


@tool("show_model", 'args {"name": "<model name, empty for the latest>"} - show a 3D model on the hologram; for "show the bracket", "show it on the hologram"')
def show_model(args):
    return f"Showing {holo.show(args.get('name') or '')} on the hologram."


@tool("reset_holo", 'args {} - put the hologram view back to its start position; for "reset the hologram"')
def reset_holo(args):
    holo.reset()
    return "The hologram view is reset."


@tool("close_holo", 'args {} - close the hologram viewer and release the camera; for "close holo"')
def close_holo(args):
    holo.close()
    return "The hologram is closed."
