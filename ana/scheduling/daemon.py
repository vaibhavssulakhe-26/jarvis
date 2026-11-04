"""Background runner: announces reminders even when nobody is talking to Ana."""
import time

from . import reminders


def main():
    print("ana reminders service started")
    reminders.watch(reminders.notify)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
