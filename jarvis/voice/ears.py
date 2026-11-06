"""Jarvis's ears: wake word, and recording one command for speech to text."""
import atexit
import collections
import difflib
import os
import queue
import random
import re
import shutil
import subprocess
import time
import traceback

import numpy as np
import sounddevice as sd
from scipy.signal import lfilter

from ..actions import events
from ..core import config, state
from . import stt, voice

SR = stt.SR
BLOCK = 1280  # 80 ms of audio per step

OPENER = r"(?:can|could|would|will) you(?: please)?|please|i (?:want|need) you to|okay|hey|so|and|um|uh"
FILLER = {"hey", "hi", "hello", "okay", "ok", "yo", "jarvis"}
NAME_ALIASES = {"jarvis", "jarvas", "jarves", "jarvus", "jervis", "service", "jarvi"}
NOISE = {"you", "thank you", "thanks", "thanks for watching", "bye", "okay", "ok",
         "yeah", "hmm", "mm", "uh", "um", "oh", "the", "so", "and"}
WAKE_WORDS = {n.split()[-1].lower() for n in config.wake_names()} or {"jarvis"}

VERBS = {"open", "play", "pause", "stop", "resume", "send", "call", "remind", "mute", "unmute",
         "lock", "search", "find", "write", "create", "close", "show", "take", "turn", "set",
         "volume", "what", "how", "when", "who", "where", "next", "skip", "save", "read",
         "draft", "message", "text"}


def block_rms(block):
    """Loudness of one audio block. The standard deviation ignores any constant offset."""
    return float(np.std(block.astype(np.float32) / 32768.0))


def is_name(word):
    w = re.sub(r"[^a-z]", "", word.lower())
    name = config.ASSISTANT.lower()
    if not w:
        return False
    if w == name or w in NAME_ALIASES:
        return True
    return abs(len(w) - len(name)) <= 1 and difflib.SequenceMatcher(None, w, name).ratio() >= 0.8


def is_wake_word(word, cutoff):
    w = re.sub(r"[^a-z]", "", word.lower())
    return bool(w) and any(difflib.SequenceMatcher(None, w, k).ratio() >= cutoff for k in WAKE_WORDS)


def strip_wake(text):
    """Remove a leading 'hey jarvis' that the transcription picked up."""
    words = text.strip().split()
    i = 0
    while i < len(words):
        w = re.sub(r"[^a-z]", "", words[i].lower())
        if w and (w in FILLER or is_name(w) or is_wake_word(w, 0.65)):
            i += 1
        else:
            break
    return " ".join(words[i:]).strip(" ,.")


def is_noise(text):
    t = re.sub(r"[^a-z ]", "", text.lower()).strip()
    return len(t) < 2 or t in NOISE


def make_chime():
    path = config.runtime_file(f"chime_{os.getpid()}.wav")
    parts = []
    for freq, dur in ((880.0, 0.09), (1174.7, 0.12)):
        n = int(SR * dur)
        t = np.arange(n) / SR
        env = np.clip(np.minimum(t / 0.01, (dur - t) / 0.04), 0.0, 1.0)
        parts.append(0.22 * np.sin(2 * np.pi * freq * t) * env)
    path.write_bytes(stt.wav_bytes(np.concatenate(parts)))
    atexit.register(config.discard, path)
    return str(path)


def play_chime(path):
    player = voice.player()
    if state.get("muted") or player is None:
        return
    subprocess.Popen([player, path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def media_playing():
    if shutil.which("playerctl") is None:
        return False
    try:
        r = subprocess.run(["playerctl", "status"], capture_output=True, text=True, timeout=1.5)
        return r.stdout.strip() == "Playing"
    except (OSError, subprocess.SubprocessError):
        return False


class Ears:
    def __init__(self, on_command):
        """on_command(text, via_wake) runs for each command; return True if you expect a reply."""
        self.on_command = on_command
        self.q = queue.Queue(maxsize=400)
        self.noise = collections.deque(maxlen=600)
        self.pre = collections.deque(maxlen=3)
        self.thr = 0.02
        self.n = 0
        self.reported = False
        self.phase = None
        self.buf = []
        self.t0 = 0.0
        self.loud = 0
        self.quiet = 0
        self.chimed = False
        self.via_wake = True
        self.expect = False
        self.awake_until = 0.0
        self.cool_until = 0.0
        self.deaf_until = 0.0
        self.last_talk = state.read()["talk_request"]
        try:
            self.wake_thr = float(config.get("WAKE_THRESHOLD", "0.4"))
        except ValueError:
            self.wake_thr = 0.4
        self.zi = np.zeros(1)
        try:
            self.gain = float(config.get("MIC_GAIN", "4"))
        except ValueError:
            self.gain = 4.0
        self.oww = self._load_wake()
        self.chime = make_chime()

    def _load_wake(self):
        from openwakeword.model import Model
        files = config.wake_files()
        if not files:
            raise SystemExit("No wake word model in " + str(config.MODELS))
        return Model(wakeword_model_paths=[str(p) for p in files])

    # ---------- listening ----------
    def _callback(self, indata, frames, t, status):
        x = indata.flatten().astype(np.float32) / 32768.0
        y, self.zi = lfilter([1.0, -1.0], [1.0, -0.995], x, zi=self.zi)
        y = np.clip(y * self.gain, -1.0, 1.0)
        block = (y * 32767).astype(np.int16)
        try:
            self.q.put_nowait(block)
        except queue.Full:
            pass

    def _drain(self):
        while True:
            try:
                self.q.get_nowait()
            except queue.Empty:
                return

    def _reset_wake(self):
        fn = getattr(self.oww, "reset", None)
        if fn:
            try:
                fn()
            except Exception:
                pass

    def _reset(self):
        self.phase = None
        self.buf = []
        self.pre.clear()
        self.loud = 0
        self.quiet = 0

    def _begin(self, now, phase, preroll=None):
        self.phase = phase
        self.t0 = now
        self.buf = list(preroll or [])
        self.loud = 0
        self.quiet = 0
        self.chimed = False

    def _after(self, seconds):
        time.sleep(0.3)
        self._drain()
        self._reset_wake()
        self.awake_until = time.time() + seconds

    def run(self):
        stt.warm()
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                blocksize=BLOCK, callback=self._callback)
        stream.start()
        where = "Groq" if stt.CLOUD else "this laptop"
        print(f"  listening for {config.wake_label().title()} (threshold {self.wake_thr}); "
              f"speech is transcribed on {where}. Ctrl+C to stop.")
        try:
            while True:
                try:
                    block = self.q.get(timeout=0.5)
                except queue.Empty:
                    continue
                self._step(block)
        except KeyboardInterrupt:
            print("\n  bye")
        finally:
            stream.stop()
            stream.close()

    def _step(self, block):
        now = time.time()
        st = state.read()
        if st["paused"] or voice.SPEAKING.is_set():
            self._drain()
            self._reset()
            return
        if now < self.deaf_until:
            return
        rms = block_rms(block)
        events.set_level(rms)
        if st["talk_request"] > self.last_talk:
            self.last_talk = st["talk_request"]
            self.via_wake = True
            self._begin(now, "wait")
            return
        if self.phase is None:
            self._idle(block, rms, now)
        elif self.phase == "wait":
            self._waiting(block, rms, now)
        else:
            self._recording(block, rms, now)

    def _idle(self, block, rms, now):
        self.noise.append(rms)
        self.pre.append(block)
        self.n += 1
        if self.n % 25 == 0 and len(self.noise) >= 50:
            floor = float(np.percentile(self.noise, 10))
            self.thr = min(0.25, max(0.015, 3.0 * floor))
            if not self.reported:
                self.reported = True
                print(f"  background {floor:.3f}, speech threshold {self.thr:.3f}")
                if floor > 0.05:
                    print("  the background is loud; lowering the microphone helps: "
                          "wpctl set-volume @DEFAULT_AUDIO_SOURCE@ 0.5")
        scores = self.oww.predict(block)
        score = max(scores.values()) if scores else 0.0
        if score > self.wake_thr and now > self.cool_until:
            self.cool_until = now + 1.5
            print(f"  wake (score {score:.2f})")
            events.emit("sys", "wake word heard")
            self.via_wake = True
            self._begin(now, "wait")
        elif now < self.awake_until:
            if rms > self.thr:
                self.loud += 1
                if self.loud >= 2:
                    self.loud = 0
                    if media_playing():
                        self.awake_until = 0.0
                    else:
                        self.via_wake = False
                        self._begin(now, "record", list(self.pre))
            else:
                self.loud = 0

    def _waiting(self, block, rms, now):
        self.buf.append(block)
        self.loud = self.loud + 1 if rms > self.thr else 0
        if self.loud >= 2:
            self.phase = "record"
            self.quiet = 0
            return
        if len(self.buf) > 6:
            del self.buf[:-6]
        waited = now - self.t0
        if waited > 1.2 and not self.chimed:
            self.chimed = True
            play_chime(self.chime)
            self.deaf_until = now + 0.45
        elif waited > 7.0:
            print("  (no command heard)")
            self._reset()
            self._reset_wake()

    def _recording(self, block, rms, now):
        self.buf.append(block)
        self.quiet = self.quiet + 1 if rms < self.thr * 0.7 else 0
        if self.quiet >= 10 or len(self.buf) >= 150:
            audio = np.concatenate(self.buf).astype(np.float32) / 32768.0
            via = self.via_wake
            self._reset()
            if len(audio) >= int(0.5 * SR):
                try:
                    self._handle(audio, via)
                except Exception:
                    traceback.print_exc()
                    voice.say("Something broke on my side, but I am still here.")
            self._drain()
            self._reset_wake()

    def _handle(self, audio, via_wake):
        t0 = time.time()
        raw = stt.transcribe(audio)
        t1 = time.time()
        text = strip_wake(raw)
        bare = re.sub(r"[^a-z ]", "", text.lower()).strip()
        named = any(is_name(w) or is_wake_word(w, 0.7) for w in raw.split()[:3])
        if not bare:
            if via_wake or named:
                print("  (nothing after the wake word)")
                voice.say(random.choice(["Yes?", "I am here.", "Go ahead."]))
                voice.wait()
                self.expect = True
                self._after(10)
            else:
                print(f"  (ignored: {repr(raw)})")
            return
        if re.fullmatch(OPENER, bare):
            print("  (waiting for the rest of the sentence)")
            self.expect = True
            self._after(10)
            return
        if not self.expect:
            if is_noise(text):
                print(f"  (ignored: {repr(text)})")
                return
            if not via_wake and len(bare.split()) < 3 and bare.split()[0] not in VERBS:
                print(f"  (ignored a short remark: {repr(text)})")
                return
        print(f"heard: {repr(text)}")
        events.emit("you", text)
        t2 = time.time()
        self.expect = bool(self.on_command(text, via_wake or named))
        print(f"  [speech to text {t1 - t0:.1f}s, thinking and acting {time.time() - t2:.1f}s]")
        voice.wait()
        asked = voice.LAST[0].strip().endswith("?")
        self._after(20 if (self.expect or asked) else 9)


def _demo(text, via_wake):
    voice.say("I heard: " + text)
    return False


if __name__ == "__main__":
    state.update(paused=False)
    voice.say("Ears test. Say Hey Jarvis, then a short sentence.")
    voice.wait()
    Ears(_demo).run()
