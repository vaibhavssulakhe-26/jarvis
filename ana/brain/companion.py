"""Ana speaks up by herself now and then: low battery, break nudges, late night."""
import random
import threading
import time
from datetime import datetime

from ..actions import tools
from ..core import config, state
from ..voice import voice

JOKES = [
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are only ten kinds of people: those who understand binary, and those who do not.",
    "A SQL query walks into a bar, walks up to two tables and asks: can I join you?",
    "Why was the laptop cold? It left its Windows open.",
    "Debugging is being the detective in a crime movie where you are also the culprit.",
    "I told my computer I needed a break, and now it keeps showing me vacation ads.",
]


def _quiet():
    return state.get("paused") or state.get("muted") or voice.SPEAKING.is_set()


def start():
    if config.get("ANA_PROACTIVE", "on").lower() in ("off", "no", "0", "false"):
        return

    def loop():
        pet = config.PET_NAME or "there"
        warned = False
        night_day = None
        next_break = time.time() + 90 * 60
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
                if time.time() >= next_break:
                    next_break = time.time() + random.randint(80, 110) * 60
                    if not _quiet() and 8 <= now.hour <= 22:
                        voice.say(f"{pet}, you have been at this a while. Stretch, sip some water, and come back "
                                  "sharper. " + random.choice(JOKES))
            except Exception as e:
                print(f"  (companion check failed: {type(e).__name__})")
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()
