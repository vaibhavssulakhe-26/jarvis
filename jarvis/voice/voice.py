"""Jarvis's voice: text to speech with Piper, kept loaded in memory."""
import atexit
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave

from ..actions import events
from ..core import config, lang, state
from . import speech, voices

SPEAKING = threading.Event()
LAST = [""]
_queue = queue.Queue()
_voice = [None, None]
_gen = [0]
_proc = [None]
Full = speech.Full

PRONOUNCE = [(r"\bVibe\b", "Vyb"), (r"\bVibeo\b", "Vybee")]
PLAYERS = ("pw-play", "paplay", "aplay")
_player = []


def pronounce(text):
    for pattern, spoken in PRONOUNCE:
        text = re.sub(pattern, spoken, text)
    return text


def _load(path=None):
    path = path or voices.current_path()
    if path is None:
        raise FileNotFoundError("no voice installed")
    if _voice[0] is None or _voice[1] != path:
        from piper import PiperVoice
        _voice[0], _voice[1] = PiperVoice.load(str(path)), path
    return _voice[0]


def synth(text, wav_path):
    """Write text as speech to wav_path. Returns True on success."""
    path = voices.path_for(text)
    try:
        voice = _load(path)
        with wave.open(wav_path, "wb") as f:
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, f)
            else:
                voice.synthesize(text, f)
        return True
    except Exception as e:
        print(f"  (fast voice failed: {type(e).__name__}, using the slower one)")
    try:
        r = subprocess.run([sys.executable, "-m", "piper", "-m", str(path),
                            "-f", wav_path], input=text.encode(), capture_output=True)
        return r.returncode == 0
    except OSError:
        return False


def player():
    if not _player:
        _player.append(next((p for p in PLAYERS if shutil.which(p)), None))
    return _player[0]


def play(wav_path, gen):
    """Play a file; stop() or the stop key cuts it off at once."""
    cmd = player()
    if cmd is None:
        return False
    started = time.time()
    proc = subprocess.Popen([cmd, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _proc[0] = proc
    while proc.poll() is None:
        if gen != _gen[0]:
            proc.kill()
        elif float(state.get("stop_at") or 0) > started:
            stop()
        time.sleep(0.05)
    return True


def stop():
    """Cut the speech now and drop what is queued. Harmless when nothing is playing; True if something was cut."""
    was = SPEAKING.is_set() or not _queue.empty()
    _gen[0] += 1
    while True:
        try:
            _queue.get_nowait()
        except queue.Empty:
            break
    proc = _proc[0]
    if proc is not None and proc.poll() is None:
        proc.kill()
    return was


def _worker():
    wav = str(config.runtime_file(f"say_{os.getpid()}.wav"))
    atexit.register(config.discard, wav)
    while True:
        gen, text = _queue.get()
        if gen == _gen[0]:
            SPEAKING.set()
            state.update(activity="speaking", activity_at=time.time())
        try:
            for part in speech.sentences(pronounce(text)) if gen == _gen[0] else ():
                if gen == _gen[0] and synth(part, wav) and gen == _gen[0]:
                    play(wav, gen)
        except Exception as e:
            print(f"  (voice error: {type(e).__name__})")
        finally:
            if gen == _gen[0]:
                time.sleep(0.35)
            if _queue.empty():
                SPEAKING.clear()
                state.update(activity="idle", activity_at=time.time())


threading.Thread(target=_worker, daemon=True).start()


def _no_kannada(text):
    """No Kannada voice is installed: the text stays on screen and goes to the clipboard, and the spoken part is English."""
    from ..actions.screen import write_clip
    copied = write_clip(text)
    say("I cannot speak Kannada yet, so the text is on screen" + (" and on your clipboard." if copied else "."))


def say(text):
    """Print a line and speak it, unless Jarvis is muted. Long or structured text stays on screen and is copied."""
    full = isinstance(text, speech.Full)
    text = str(text).strip()
    if not text:
        return
    LAST[0] = text
    print(f"  {text}")
    events.emit("jarvis", text)
    if lang.script(text) == "kn" and voices.for_language("kn") is None:
        _no_kannada(text)
        return
    if full:
        spoken = speech.clean(text)
    elif speech.too_long(text):
        from ..actions.screen import write_clip
        spoken = speech.DONE if write_clip(text) else "Done, it's on your screen."
    else:
        spoken = speech.shorten(speech.clean(text))
    if not spoken or state.get("muted") or voices.current_path() is None:
        return
    SPEAKING.set()
    _queue.put((_gen[0], spoken))


def wait():
    while SPEAKING.is_set() or not _queue.empty():
        time.sleep(0.1)


def warm():
    """Load the voice in the background so the first sentence is not slow."""
    def go():
        try:
            _load()
        except Exception as e:
            print(f"  (could not load the voice: {type(e).__name__})")
    threading.Thread(target=go, daemon=True).start()


if __name__ == "__main__":
    if sys.argv[1:] == ["--stop"]:
        state.update(stop_at=time.time())
        sys.exit(0)
    say(" ".join(sys.argv[1:]) or "Hello, I am Jarvis. This is my fresh start.")
    wait()
