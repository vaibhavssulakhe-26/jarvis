"""Dictation: hold a key, speak, release, and the text is pasted into the focused window.
DICTATE_KEY names the key (for example F9 or RIGHTCTRL); empty keeps it off. Reading keys needs membership of the input group.
Without that, bind `python -m jarvis.voice.dictate --once` to a KDE shortcut: it records until you stop talking."""
import shutil
import subprocess
import sys
import threading
import time

import numpy as np

from ..core import config, state
from . import stt

MAX_SECONDS = 60
SILENCE_SECONDS = 1.2
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "xterm", "wezterm", "foot", "yakuake")
_busy = threading.Lock()
_hint = [False]


def key_name():
    """The evdev key name for DICTATE_KEY, such as KEY_F9, or None when dictation is off."""
    raw = config.get("DICTATE_KEY").strip().upper().replace(" ", "")
    if not raw or raw in ("OFF", "NONE", "FALSE", "0"):
        return None
    return raw if raw.startswith("KEY_") else "KEY_" + raw


def key_code(name=None):
    from evdev import ecodes
    name = name or key_name()
    return getattr(ecodes, name, None) if name else None


def set_dictating(on):
    state.update(dictating=bool(on))


def paste(text):
    """Copy text with wl-copy and press the paste shortcut in the focused window. Returns True if the keys were sent."""
    if not shutil.which("wl-copy"):
        raise RuntimeError("wl-copy is missing")
    subprocess.run(["wl-copy"], input=text.encode(), timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shift = False
    try:
        from ..actions import windows
        win = windows.active_window()
        shift = bool(win) and any(t in win[0].lower() for t in TERMINALS)
    except Exception:
        pass
    from evdev import UInput, ecodes as e
    ui = UInput({e.EV_KEY: [e.KEY_LEFTCTRL, e.KEY_LEFTSHIFT, e.KEY_V]}, name="jarvis-dictation")
    try:
        time.sleep(0.3)
        keys = [e.KEY_LEFTCTRL] + ([e.KEY_LEFTSHIFT] if shift else []) + [e.KEY_V]
        for k in keys:
            ui.write(e.EV_KEY, k, 1)
        ui.syn()
        time.sleep(0.05)
        for k in reversed(keys):
            ui.write(e.EV_KEY, k, 0)
        ui.syn()
        time.sleep(0.1)
    finally:
        ui.close()
    return True


def finish(audio, say=None):
    """Transcribe one recording and paste the result. Returns the text, or '' when nothing was understood."""
    text = " ".join(stt.transcribe(audio).split())
    if not text:
        if say:
            say("I did not catch that.")
        return ""
    try:
        paste(text)
    except Exception as e:
        print(f"  (could not paste: {type(e).__name__}); the text is on the clipboard if wl-copy ran")
        if say:
            say("I could not paste it. Look on your clipboard.")
    return text


class Keyboard:
    """Press starts a recording, release ends it. handle(event_type, code, value) takes raw evdev values."""

    def __init__(self, code, open_stream=None, say=None):
        self.code = code
        self.open_stream = open_stream or self._stream
        self.say = say
        self.stream = None
        self.chunks = []
        self.started = 0.0

    def _stream(self, callback):
        import sounddevice as sd
        return sd.InputStream(samplerate=stt.SR, channels=1, dtype="float32", callback=callback)

    def _on_audio(self, indata, frames, t, status):
        self.chunks.append(indata.copy().flatten())

    def handle(self, ev_type, code, value):
        from evdev import ecodes
        if ev_type != ecodes.EV_KEY or code != self.code:
            return
        if value == 1 and self.stream is None:
            self.begin()
        elif value == 0 and self.stream is not None:
            self.end()

    def begin(self):
        self.chunks = []
        self.started = time.time()
        set_dictating(True)
        self.stream = self.open_stream(self._on_audio)
        self.stream.start()

    def end(self):
        stream, self.stream = self.stream, None
        stream.stop()
        stream.close()
        chunks, self.chunks = self.chunks, []
        set_dictating(False)
        if not chunks or time.time() - self.started < 0.3:
            return
        audio = np.concatenate(chunks)[: MAX_SECONDS * stt.SR]
        threading.Thread(target=self._process, args=(audio,), daemon=True).start()

    def _process(self, audio):
        with _busy:
            try:
                finish(audio, self.say)
            except Exception as e:
                print(f"  (dictation failed: {type(e).__name__})")


def keyboards():
    """Evdev devices that look like keyboards. Raises PermissionError without input group access."""
    import evdev
    from evdev import ecodes
    found = []
    for path in evdev.list_devices():
        dev = evdev.InputDevice(path)
        keys = dev.capabilities().get(ecodes.EV_KEY, [])
        if ecodes.KEY_A in keys and ecodes.KEY_ENTER in keys and "jarvis" not in dev.name.lower():
            found.append(dev)
    return found


def listen(code, say=None):
    import selectors
    kb = Keyboard(code, say=say)
    sel = selectors.DefaultSelector()
    for dev in keyboards():
        sel.register(dev, selectors.EVENT_READ)
    if not sel.get_map():
        raise RuntimeError("no keyboard found")
    while True:
        for key, _ in sel.select():
            for ev in key.fileobj.read():
                kb.handle(ev.type, ev.code, ev.value)


def start(say=None):
    """Start the hotkey listener in the background when DICTATE_KEY is set. Returns the thread, or None."""
    name = key_name()
    if not name:
        return None
    try:
        code = key_code(name)
    except ImportError:
        print("  (dictation needs the evdev package)")
        return None
    if code is None:
        print(f"  (DICTATE_KEY {name} is not a known key name)")
        return None

    def run():
        try:
            listen(code, say)
        except PermissionError:
            print("  (dictation cannot read the keyboard. Run: sudo usermod -aG input $USER, then log out and in. "
                  "Or bind python -m jarvis.voice.dictate --once to a KDE shortcut.)")
        except Exception as e:
            print(f"  (dictation stopped: {type(e).__name__})")
    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread


def record_once(open_stream=None, now=time.time):
    """Record until about a second of quiet after speech (or MAX_SECONDS). For the shortcut mode."""
    chunks, heard, quiet_since = [], False, None
    start_t = now()

    def cb(indata, frames, t, status):
        chunks.append(indata.copy().flatten())
    if open_stream is None:
        import sounddevice as sd
        stream = sd.InputStream(samplerate=stt.SR, channels=1, dtype="float32", callback=cb)
    else:
        stream = open_stream(cb)
    stream.start()
    try:
        seen = 0
        while now() - start_t < MAX_SECONDS:
            time.sleep(0.1)
            new, seen = chunks[seen:], len(chunks)
            for block in new:
                if float(np.std(block)) > 0.01:
                    heard, quiet_since = True, None
                elif heard and quiet_since is None:
                    quiet_since = now()
            if heard and quiet_since is not None and now() - quiet_since >= SILENCE_SECONDS:
                break
            if not heard and now() - start_t > 8:
                break
    finally:
        stream.stop()
        stream.close()
    return np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv != ["--once"]:
        print("usage: python -m jarvis.voice.dictate --once")
        return 2
    set_dictating(True)
    try:
        audio = record_once()
    finally:
        set_dictating(False)
    return 0 if finish(audio) else 1


if __name__ == "__main__":
    sys.exit(main())
