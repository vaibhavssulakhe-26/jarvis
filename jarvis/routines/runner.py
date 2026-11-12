"""Runs routines inside the app: missed ones at startup, then a check every five minutes. The systemd timer does the same
job when the app is closed; the file lock in routines/__init__ keeps the two from running one routine twice."""
import threading
import time
from datetime import date, datetime

from ..memory import store
from ..scheduling import reminders
from . import morning, run_due

CHECK_SECONDS = 300


def announce(speak, now=None):
    """Speak today's briefing once per day (three sentences at most), unless it is quiet hours or the old digest already spoke."""
    now = now or datetime.now()
    got = morning.latest(now.date())
    if not got or not got["spoken"] or reminders.in_quiet(now):
        return False
    if not store.claim("digest_last", date.today().isoformat()):
        return False
    store.set_meta("briefing_spoken", date.today().isoformat())
    speak(got["spoken"])
    return True


def start(speak, first_delay=15):
    def loop():
        time.sleep(first_delay)
        first = True
        while True:
            try:
                run_due()
                if first:
                    announce(speak)
                    first = False
            except Exception as e:
                print(f"  (routines failed: {type(e).__name__})")
            time.sleep(CHECK_SECONDS)
    threading.Thread(target=loop, daemon=True).start()
