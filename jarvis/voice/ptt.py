"""Push to talk: hold PTT_KEY (or the Talk button), speak, release. While it is held no wake word is needed.
`held()` is what Ears looks at; the key listener and the dashboard button call press() and release()."""
import threading
import time

from .. import platform
from ..core import config
from ..core.errors import ToolError

_held = threading.Event()
_since = [0.0]


def key_name():
    """The key name for PTT_KEY, such as KEY_RIGHTCTRL, or None when no key is set."""
    raw = config.get("PTT_KEY").strip().upper().replace(" ", "")
    if not raw or raw in ("OFF", "NONE", "FALSE", "0"):
        return None
    return raw if raw.startswith("KEY_") else "KEY_" + raw


def press():
    _since[0] = time.time()
    _held.set()


def release():
    _held.clear()


def held():
    return _held.is_set()


def start():
    """Listen for PTT_KEY in the background. Returns the thread, or None when no key is set."""
    name = key_name()
    if not name:
        return None

    def run():
        try:
            platform.listen_key(name, press, release)
        except PermissionError:
            print("  (push to talk cannot read the keyboard. Run: sudo usermod -aG input $USER, then log out and in. "
                  "The Talk button in the window works without it.)")
        except ImportError:
            print("  (push to talk needs the evdev package)")
        except ToolError as e:
            print(f"  ({e})")
        except Exception as e:
            print(f"  (push to talk stopped: {type(e).__name__})")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
