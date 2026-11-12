"""One interface for everything that differs between operating systems: clipboard, opening things, screenshots, windows, notifications,
power, volume, brightness, media keys, autostart and scheduling, global hotkeys, audio players and the runtime, state and data folders.
Each backend (linux.py, mac.py) implements what it can. A function a backend does not have raises Unsupported, whose message is
speakable ("... is not supported on this system"), so a missing feature is a clear sentence, never a crash.
Only the standard library is used here, because config.py imports this package before anything else."""
import sys

from ..core.errors import ToolError

API = (
    # folders
    "runtime_dir", "lock_dir", "state_dir", "data_dir",
    # clipboard
    "clipboard_read", "clipboard_write", "clipboard_write_image", "clipboard_watch_ok",
    # opening and capturing
    "open_target", "open_ok", "capture_screen",
    # windows
    "windows_ok", "active_window", "window_find", "window_close", "window_activate", "close_active", "minimise_active",
    # notifications and power
    "notify", "inhibit_notifications", "lock_screen", "power",
    # sound and display
    "volume_get", "volume_set", "volume_change", "unmute", "brightness_change", "brightness_set", "media_control", "media_status",
    "audio_players", "alarm_sound",
    # keyboard
    "listen_key", "send_paste", "send_enter",
    # background services
    "service_active", "install_schedule", "install_autostart",
)


class Unsupported(ToolError):
    def __init__(self, feature, hint=""):
        super().__init__(f"{feature} is not supported on this system." + (f" {hint}" if hint else ""))


def _pick():
    from . import linux, mac
    return mac if sys.platform == "darwin" else linux


_backend = [None]


def backend():
    if _backend[0] is None:
        _backend[0] = _pick()
    return _backend[0]


def use(module):
    """Swap the backend (the checks use this to run the interface with a mocked backend)."""
    _backend[0] = module


def name():
    return getattr(backend(), "NAME", "unknown")


def _api(func):
    def call(*args, **kwargs):
        impl = getattr(backend(), func, None)
        if impl is None:
            raise Unsupported(func.replace("_", " "))
        return impl(*args, **kwargs)
    call.__name__ = func
    call.__doc__ = f"Backend call {func}; Unsupported when the backend lacks it."
    return call


for _name in API:
    globals()[_name] = _api(_name)
