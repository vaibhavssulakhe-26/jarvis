"""The focused window (app, title) and simple window actions, read locally. Used by notes, the distraction guard and the app tools.
The work is done by the platform backend."""
from .. import platform


def available():
    return platform.windows_ok()


def active_window(max_age=2.0):
    """(app, title) of the focused window, or None when it cannot be read."""
    try:
        return platform.active_window(max_age)
    except platform.Unsupported:
        return None


def find_ids(patterns):
    return platform.window_find(patterns)


def close(ids):
    platform.window_close(ids)


def activate(wid):
    platform.window_activate(wid)


def close_active():
    platform.close_active()


def minimise_active():
    platform.minimise_active()
