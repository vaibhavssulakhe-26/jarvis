"""Open or show what "it" or "that" refers to: the last model, file or project."""
from .. import holo, platform
from ..core import refs
from ..core.errors import ToolError
from .tools import tool


@tool("open_last", 'args {"holo": true when the hologram was asked for} - open or show the last model, file or project: "it", "that", "this"; for "open that", "show it", "view it in hologram"')
def open_last(args):
    on_holo = bool(args.get("holo"))
    ref = refs.latest(("model",) if on_holo else refs.KINDS)
    if ref is None:
        raise ToolError("I have no model to show yet. Make one, or say its name." if on_holo else "I do not know what you mean by that. Say the name of the file, model or project.")
    if ref["kind"] == "model":
        if on_holo or holo.ready():
            return f"Showing {holo.show(ref['name'])} on the hologram."
        platform.open_target(ref["path"])
        return f"Opening the model {ref['name'].replace('-', ' ')}."
    platform.open_target(ref["path"])
    return f"Opening {ref['name']}."
