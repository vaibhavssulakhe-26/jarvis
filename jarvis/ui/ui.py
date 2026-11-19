"""What the dashboard window needs from the app: start the voice loop, and shut everything down."""
import threading
import traceback

from .. import platform
from ..actions import browser, events, mpvctl, procs
from ..brain import brain
from ..core import main as core


def shutdown_all():
    """Kill mpv, the controlled browser and every child process, and save the conversation summary."""
    mpvctl.stop()
    procs.stop_all()
    browser.shutdown()
    brain.finish()


def service_active(name):
    return platform.service_active(name)


def start_core():
    background = service_active("jarvis-reminders") or service_active("jarvis")
    if background:
        events.emit("sys", "reminders are handled by a background service")
    core.start(watch_reminders=not background)

    def run():
        try:
            core.listen()
        except SystemExit as e:
            events.emit("sys", str(e))
        except Exception as e:
            events.emit("sys", f"my ears stopped: {type(e).__name__}")
            traceback.print_exc()

    threading.Thread(target=run, daemon=True).start()
