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

from .. import platform
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
        scale = voices.length_scale()
        with wave.open(wav_path, "wb") as f:
            if hasattr(voice, "synthesize_wav"):
                from piper import SynthesisConfig
                voice.synthesize_wav(text, f, syn_config=SynthesisConfig(length_scale=scale))
            else:
                voice.synthesize(text, f)
        return True
    except Exception as e:
        print(f"  (fast voice failed: {type(e).__name__}, using the slower one)")
    try:
        r = subprocess.run([sys.executable, "-m", "piper", "-m", str(path), "--length-scale", str(voices.length_scale()),
                            "-f", wav_path], input=text.encode(), capture_output=True)
        return r.returncode == 0
    except OSError:
        return False


def player():
    if not _player:
        _player.append(next((p for p in platform.audio_players() if shutil.which(p)), None))
    return _player[0]


def envelope(wav_path, step=0.05):
    """Loudness of the file every 50 ms, 0 to 1, so the window can ripple with what is being said."""
    try:
        import numpy as np
        with wave.open(wav_path, "rb") as f:
            raw = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
            size = max(1, int(f.getframerate() * step))
        n = len(raw) // size
        if n == 0:
            return []
        rms = np.sqrt((raw[: n * size].reshape(n, size) ** 2).mean(axis=1))
        return [float(min(1.0, v * 6)) for v in rms]
    except Exception:
        return []


def play(wav_path, gen):
    """Play a file; stop() or the stop key cuts it off at once."""
    cmd = player()
    if cmd is None:
        return False
    started = time.time()
    env = envelope(wav_path)
    proc = subprocess.Popen([cmd, wav_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    _proc[0] = proc
    while proc.poll() is None:
        i = int((time.time() - started) / 0.05)
        events.set_out_level(env[i] if i < len(env) else 0.0)
        if gen != _gen[0]:
            proc.kill()
        elif float(state.get("stop_at") or 0) > started:
            stop()
        time.sleep(0.05)
    events.set_out_level(0.0)
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


def _speak(parts, wav, gen):
    """Speak sentence by sentence. The first one starts as soon as it is synthesised; the next is made while it plays."""
    spare = wav.replace(".wav", "_next.wav")
    atexit.register(config.discard, spare)
    ready = {}

    def make(i, path):
        ready[i] = synth(parts[i], path)

    maker = None
    current = wav
    make(0, current)
    for i in range(len(parts)):
        if gen != _gen[0]:
            break
        following = spare if current == wav else wav
        if i + 1 < len(parts):
            maker = threading.Thread(target=make, args=(i + 1, following), daemon=True)
            maker.start()
        if ready.get(i):
            play(current, gen)
        if maker is not None:
            maker.join()
            maker = None
        current = following


def _worker():
    wav = str(config.runtime_file(f"say_{os.getpid()}.wav"))
    atexit.register(config.discard, wav)
    while True:
        gen, text = _queue.get()
        if gen == _gen[0]:
            SPEAKING.set()
            state.update(activity="speaking", activity_at=time.time())
        try:
            parts = speech.sentences(pronounce(text)) if gen == _gen[0] else ()
            if parts:
                _speak(parts, wav, gen)
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
        from ..actions import mpvctl
        mpvctl.stop()
        sys.exit(0)
    say(" ".join(sys.argv[1:]) or "Hello, I am Jarvis. This is my fresh start.")
    wait()
