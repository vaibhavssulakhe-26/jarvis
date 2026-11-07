"""Jarvis speaks up by itself for a low battery and for late nights. Chatty check-ins are in scheduling/proactive.py."""
import threading
import time
from datetime import datetime

from ..actions import tools
from ..core import config, state
from ..voice import voice


def _quiet():
    return state.get("paused") or state.get("muted") or voice.SPEAKING.is_set()


def start():
    if config.get("JARVIS_PROACTIVE", "on").lower() in ("off", "no", "0", "false"):
        return

    def loop():
        pet = config.PET_NAME or "there"
        warned = False
        night_day = None
        time.sleep(60)
        while True:
            try:
                pct, status = tools.read_battery()
                if pct is not None:
                    if status == "discharging" and pct <= 20 and not warned and not _quiet():
                        warned = True
                        voice.say(f"Heads up, {pet}. Battery is at {pct} percent and not charging. Charger time.")
                    elif status != "discharging" or pct >= 35:
                        warned = False
                now = datetime.now()
                if now.hour >= 23 and night_day != now.date() and not _quiet():
                    night_day = now.date()
                    voice.say(f"It is past eleven, {pet}. Your code will still be broken tomorrow, "
                              "but you will be much better at fixing it after sleep.")
            except Exception as e:
                print(f"  (companion check failed: {type(e).__name__})")
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()
