"""Dictation: hold a key, speak, release, and the text is pasted into the focused window.
DICTATE_KEY names the key (for example F9 or RIGHTCTRL); empty keeps it off. Reading keys needs membership of the input group.
Without that, bind `python -m jarvis.voice.dictate --once` to a KDE shortcut: it records until you stop talking."""
import sys
import threading
import time

import numpy as np

from .. import platform
from ..core import config, state
from ..core.errors import ToolError
from . import stt

MAX_SECONDS = 60
SILENCE_SECONDS = 1.2
TERMINALS = ("konsole", "terminal", "kitty", "alacritty", "xterm", "wezterm", "foot", "yakuake")
_busy = threading.Lock()
_hint = [False]


def key_name():
    """The key name for DICTATE_KEY, such as KEY_F9, or None when dictation is off."""
    raw = config.get("DICTATE_KEY").strip().upper().replace(" ", "")
    if not raw or raw in ("OFF", "NONE", "FALSE", "0"):
        return None
    return raw if raw.startswith("KEY_") else "KEY_" + raw


def set_dictating(on):
    state.update(dictating=bool(on))


def paste(text):
    """Put text on the clipboard and press the paste shortcut in the focused window."""
    if not platform.clipboard_write(text):
        raise RuntimeError("no clipboard tool is available")
    shift = False
    try:
        from ..actions import windows
        win = windows.active_window()
        shift = bool(win) and any(t in win[0].lower() for t in TERMINALS)
    except Exception:
        pass
    time.sleep(0.3)
    platform.send_paste(terminal=shift)
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
        print(f"  (could not paste: {type(e).__name__}); the text is on the clipboard if a clipboard tool ran")
        if say:
            say("I could not paste it. Look on your clipboard.")
    return text


class Keyboard:
    """press() starts a recording and release() ends it; the platform key listener calls them."""

    def __init__(self, open_stream=None, say=None):
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

    def press(self):
        if self.stream is None:
            self.begin()

    def release(self):
        if self.stream is not None:
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


def listen(name, say=None):
    kb = Keyboard(say=say)
    platform.listen_key(name, kb.press, kb.release)


def start(say=None):
    """Start the hotkey listener in the background when DICTATE_KEY is set. Returns the thread, or None."""
    name = key_name()
    if not name:
        return None

    def run():
        try:
            listen(name, say)
        except PermissionError:
            print("  (dictation cannot read the keyboard. Run: sudo usermod -aG input $USER, then log out and in. "
                  "Or bind python -m jarvis.voice.dictate --once to a keyboard shortcut.)")
        except ImportError:
            print("  (dictation needs the evdev package)")
        except ToolError as e:
            print(f"  ({e})")
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
