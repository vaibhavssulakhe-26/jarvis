"""Background runner: announces reminders even when nobody is talking to Jarvis."""
import time

from ..voice import voice
from . import digest, monitor, reminders


def main():
    print("jarvis reminders service started")
    reminders.watch(reminders.notify)
    digest.watch(voice.say)
    monitor.watch()
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
