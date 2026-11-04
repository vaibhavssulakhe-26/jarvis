"""A tiny message bus so the window can show what Ana hears and says."""
listeners = []
level = 0.0


def emit(kind, text):
    for fn in list(listeners):
        try:
            fn(kind, str(text))
        except Exception:
            pass


def set_level(value):
    global level
    level = value
