"""Voice control for the dashboard colours: 'change theme to red', 'next theme', 'random theme'."""
import time

from ..core import state
from ..ui.dashboard import themes
from .tools import ToolError, tool


@tool("change_theme", 'args {"theme": "cyan, green, amber, red, purple, pink, white, next or random"} - change the dashboard colour theme; for "change theme to red", "next theme", "random theme"')
def change_theme(args):
    name, hue, _ = themes.load()
    chosen = themes.pick(args.get("theme"), name)
    if chosen is None:
        raise ToolError("I know cyan, green, amber, red, purple, pink and white. Or say next theme.")
    themes.save(chosen)
    state.update(theme_at=time.time())
    return f"Theme changed to {chosen}."
