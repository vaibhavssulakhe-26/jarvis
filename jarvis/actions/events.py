"""A tiny message bus so the window can show what Jarvis hears and says."""
listeners = []
level = 0.0
out_level = 0.0


def emit(kind, text):
    for fn in list(listeners):
        try:
            fn(kind, str(text))
        except Exception:
            pass


def set_level(value):
    global level
    level = value


def set_out_level(value):
    global out_level
    out_level = value


busy = {}


def agent_start(group):
    busy[group] = busy.get(group, 0) + 1


def agent_end(group):
    busy[group] = max(0, busy.get(group, 0) - 1)
