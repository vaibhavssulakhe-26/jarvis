"""Ana's voice: text to speech with Piper, kept loaded in memory."""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import wave

from . import config, state

SPEAKING = threading.Event()
LAST = [""]
_queue = queue.Queue()
_voice = [None]

PRONOUNCE = [(r"\bVibee\b", "Vybee"), (r"\bVibeo\b", "Vybee"), (r"\bAna\b", "Ahna")]
PLAYERS = ("pw-play", "paplay", "aplay")


def pronounce(text):
    for pattern, spoken in PRONOUNCE:
        text = re.sub(pattern, spoken, text)
    return text


def _load():
    if _voice[0] is None:
        from piper import PiperVoice
        _voice[0] = PiperVoice.load(str(config.VOICE))
    return _voice[0]


def synth(text, wav_path):
    """Write text as speech to wav_path. Returns True on success."""
    try:
        voice = _load()
        with wave.open(wav_path, "wb") as f:
            if hasattr(voice, "synthesize_wav"):
                voice.synthesize_wav(text, f)
            else:
                voice.synthesize(text, f)
        return True
    except Exception as e:
        print(f"  (fast voice failed: {type(e).__name__}, using the slower one)")
    try:
        r = subprocess.run([sys.executable, "-m", "piper", "-m", str(config.VOICE),
                            "-f", wav_path], input=text.encode(), capture_output=True)
        return r.returncode == 0
    except OSError:
        return False


def play(wav_path):
    for player in PLAYERS:
        if shutil.which(player):
            subprocess.run([player, wav_path], stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            return True
    return False


def _worker():
    wav = f"/tmp/ana_say_{os.getpid()}.wav"
    while True:
        text = _queue.get()
        SPEAKING.set()
        state.update(activity="speaking", activity_at=time.time())
        try:
            if synth(pronounce(text), wav):
                play(wav)
        except Exception as e:
            print(f"  (voice error: {type(e).__name__})")
        finally:
            time.sleep(0.35)
            if _queue.empty():
                SPEAKING.clear()
                state.update(activity="idle", activity_at=time.time())


threading.Thread(target=_worker, daemon=True).start()


def say(text):
    """Print a line and speak it, unless Ana is muted."""
    text = str(text).strip()
    if not text:
        return
    LAST[0] = text
    print(f"  {text}")
    if state.get("muted") or not config.VOICE.exists():
        return
    SPEAKING.set()
    _queue.put(text)


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
    say(" ".join(sys.argv[1:]) or "Hello, I am Ana. This is my fresh start.")
    wait()
