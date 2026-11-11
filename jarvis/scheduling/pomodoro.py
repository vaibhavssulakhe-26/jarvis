"""Pomodoro timer: a focus stretch, then a break. State lives in the shared state file so the window can show it."""
import threading
import time

from ..core import config, state

FOCUS_DEFAULT = 25
BREAK_DEFAULT = 5
MAX_MINUTES = 180
_watcher = {"thread": None}
_inhibit = {"cookie": None}


def _dbus():
    from PyQt6.QtDBus import QDBus, QDBusConnection
    return QDBus, QDBusConnection.sessionBus()


def _call(iface, method, *args):
    from PyQt6.QtDBus import QDBusMessage
    QDBus, bus = _dbus()
    msg = QDBusMessage.createMethodCall("org.freedesktop.Notifications", "/org/freedesktop/Notifications", iface, method)
    msg.setArguments(list(args))
    return bus.call(msg, QDBus.CallMode.Block, 2000)


def mute_notifications(on):
    """Plasma's notification inhibit (do not disturb). It ends by itself if Jarvis exits. Best effort; returns True if it changed."""
    if not config.flag("FOCUS_MUTE_NOTIFICATIONS"):
        return False
    try:
        if on and _inhibit["cookie"] is None:
            reply = _call("org.freedesktop.Notifications", "Inhibit", "Jarvis", "Focus session", {})
            if reply.arguments():
                _inhibit["cookie"] = int(reply.arguments()[0])
                return True
        elif not on and _inhibit["cookie"] is not None:
            from PyQt6.QtCore import QMetaType
            from PyQt6.QtDBus import QDBusArgument
            _call("org.freedesktop.Notifications", "UnInhibit", QDBusArgument(_inhibit["cookie"], QMetaType.Type.UInt.value))
            _inhibit["cookie"] = None
            return True
    except Exception as e:
        print(f"  (could not change do not disturb: {type(e).__name__})")
    return False


def status():
    """{'kind': 'focus' or 'break', 'minutes', 'started', 'until'} while a timer runs, else None."""
    cur = state.get("pomodoro")
    return cur if isinstance(cur, dict) and float(cur.get("until", 0)) > 0 else None


def left(now=None):
    cur = status()
    return max(0.0, float(cur["until"]) - (now or time.time())) if cur else 0.0


def start(kind="focus", minutes=None, now=None):
    now = now or time.time()
    minutes = int(minutes or (FOCUS_DEFAULT if kind == "focus" else BREAK_DEFAULT))
    minutes = max(1, min(MAX_MINUTES, minutes))
    state.update(pomodoro={"kind": kind, "minutes": minutes, "started": now, "until": now + minutes * 60},
                 focus_until=now + minutes * 60 if kind == "focus" else 0.0)
    mute_notifications(kind == "focus")
    watch()
    return minutes


def elapsed_minutes(cur, now=None):
    return int(max(0.0, (now or time.time()) - float(cur["started"])) // 60)


def stop(now=None):
    """End the timer. Returns (kind, minutes that count as studied) or None when nothing ran."""
    cur = status()
    if not cur:
        return None
    done = min(int(cur["minutes"]), elapsed_minutes(cur, now)) if cur["kind"] == "focus" else 0
    state.update(pomodoro=None, focus_until=0.0)
    mute_notifications(False)
    if done:
        _credit(done)
    return cur["kind"], done


def _credit(minutes):
    from ..actions import study
    study.add_minutes(minutes)


def tick(speak, now=None):
    """Called every second: when the timer has run out, say so and credit the study time. Returns the finished kind or None."""
    now = now or time.time()
    cur = status()
    if not cur or float(cur["until"]) > now:
        return None
    state.update(pomodoro=None, focus_until=0.0)
    mute_notifications(False)
    if cur["kind"] == "focus":
        _credit(int(cur["minutes"]))
        speak(f"Focus session done, {cur['minutes']} minutes. Take a short break. Say break when you are ready, or start focus for another round.")
    else:
        speak("Break over. Say start focus when you are ready for the next one.")
    return cur["kind"]


def watch():
    """One timer thread for the process. It ends when no timer is running."""
    if _watcher["thread"] is not None and _watcher["thread"].is_alive():
        return

    def loop():
        from ..voice import voice
        while status():
            try:
                tick(voice.say)
            except Exception as e:
                print(f"  (focus timer failed: {type(e).__name__})")
            time.sleep(1)
    _watcher["thread"] = threading.Thread(target=loop, daemon=True)
    _watcher["thread"].start()


def resume():
    """After a restart: a timer that is still running keeps counting; one that ran out meanwhile is dropped quietly."""
    cur = status()
    if cur and float(cur["until"]) <= time.time():
        state.update(pomodoro=None, focus_until=0.0)
    elif cur:
        watch()
