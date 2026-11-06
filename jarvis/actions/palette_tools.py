"""Opens the command palette window."""
import subprocess
import sys

from ..core import config
from .tools import tool


@tool("open_palette", 'args {} - open the small command box; for "open palette"')
def open_palette(args):
    subprocess.Popen([sys.executable, "-m", "jarvis.ui.palette"], cwd=config.ROOT, start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return "Palette open."
