"""Runs routines inside the app: missed ones at startup, then a check every five minutes. The systemd timer does the same
job when the app is closed; the file lock in routines/__init__ keeps the two from running one routine twice."""
import threading
import time
from datetime import date, datetime

from .. import alerts, telegram
from ..actions import events
from ..memory import store
from ..scheduling import reminders
from . import find, maildigest, morning, run_due

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


def push(speak, now=None):
    """The day's briefing goes to the dashboard and the phone once, then is spoken (see announce)."""
    now = now or datetime.now()
    got = morning.latest(now.date())
    if got and store.claim("briefing_shown", now.date().isoformat()):
        events.emit("sys", got["text"])
        telegram.notify_once("briefing_pushed", got["text"])
    return announce(speak, now)


def deliver(done, speak):
    """After scheduled routines ran: push a new briefing, speak and send a new digest."""
    for name, ok, _ in done:
        routine = find(name)
        if not ok or not routine:
            continue
        if routine["action"] == "briefing":
            push(speak)
        elif routine["action"] == "maildigest":
            got = maildigest.latest()
            if got:
                events.emit("sys", got["text"])
                if got["counts"]["needs"] and not reminders.in_quiet(datetime.now()):
                    speak(got["spoken"])


def start(speak, first_delay=15):
    def loop():
        time.sleep(first_delay)
        first = True
        while True:
            try:
                deliver(run_due(), speak)
                if first:
                    push(speak)
                    first = False
            except Exception as e:
                alerts.add("routines", "the routine loop failed: " + alerts.describe(e))
            time.sleep(CHECK_SECONDS)
    threading.Thread(target=loop, daemon=True).start()
