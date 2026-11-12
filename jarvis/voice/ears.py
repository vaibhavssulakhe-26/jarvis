"""Jarvis's ears: wake word, and recording one command for speech to text."""
import atexit
import collections
import difflib
import os
import queue
import random
import re
import subprocess
import time
import traceback

import numpy as np
import sounddevice as sd
from scipy.signal import lfilter

from .. import platform, redact
from ..actions import events, mpvctl
from ..core import config, state
from ..scheduling import reminders
from . import echo, stt, voice

SR = stt.SR
BLOCK = 1280  # 80 ms of audio per step

OPENER = r"(?:can|could|would|will) you(?: please)?|please|i (?:want|need) you to|okay|hey|so|and|um|uh"
FILLER = {"hey", "hi", "hello", "okay", "ok", "yo", "jarvis"}
NAME_ALIASES = {"jarvis", "jarvas", "jarves", "jarvus", "jervis", "service", "jarvi"}
ANYWHERE_ALIASES = NAME_ALIASES - {"service"}
ROLL_BLOCKS = 50  # 4 seconds of audio kept while idle, for "play something Jarvis"
ROLL_TAIL = 14  # the last 1.1 seconds are the wake word itself
ROLL_MIN_LOUD = 4
NOISE = {"you", "thank you", "thanks", "thanks for watching", "bye", "okay", "ok",
         "yeah", "hmm", "mm", "uh", "um", "oh", "the", "so", "and"}
END = re.compile(r"^(?:ok(?:ay)? )?(?:thanks|thank you|that(?:s| is) (?:all|it)|that will be all|bye|goodbye|good bye|stop listening|"
                 r"never mind|nothing else)(?: jarvis| so much| a lot)?$")
WAKE_WORDS = {n.split()[-1].lower() for n in config.wake_names()} or {"jarvis"}

VERBS = {"open", "play", "pause", "stop", "resume", "send", "call", "remind", "mute", "unmute",
         "lock", "search", "find", "write", "create", "close", "show", "take", "turn", "set",
         "volume", "louder", "quieter", "softer", "what", "how", "when", "who", "where", "next", "skip", "save", "read",
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


def drop_name(text):
    """Remove the assistant's name wherever it stands ("play something Jarvis"). 'service' is only dropped at the start, by strip_wake."""
    name = config.ASSISTANT.lower()
    words = [w for w in text.split() if re.sub(r"[^a-z]", "", w.lower()) not in ANYWHERE_ALIASES | {name}]
    return " ".join(words).strip(" ,.")


def named_anywhere(raw):
    name = config.ASSISTANT.lower()
    return any(re.sub(r"[^a-z]", "", w.lower()) in ANYWHERE_ALIASES | {name} for w in raw.split())


def take_preroll(roll, thr):
    """Audio spoken just before the wake word, or None. `roll` is the recent blocks, newest last; the final ROLL_TAIL blocks
    are the wake word, so speech is looked for before them. The result starts a little ahead of the first loud block."""
    before = list(roll)[:-ROLL_TAIL]
    loud = [i for i, b in enumerate(before) if block_rms(b) > thr]
    if len(loud) < ROLL_MIN_LOUD:
        return None
    return list(roll)[max(0, loud[0] - 3):]


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
    t = re.sub(r"[^\w ]", "", text.lower()).strip()
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


def barge_threshold(wake):
    """Score the wake word needs to cut off speech: BARGE_THRESHOLD, else the wake threshold plus 0.3."""
    try:
        return min(0.99, float(config.get("BARGE_THRESHOLD", "")))
    except ValueError:
        return min(0.95, wake + 0.3)


def followup_seconds():
    """How long Jarvis keeps listening after a reply without the wake word (FOLLOWUP_SECONDS, default 10)."""
    try:
        return max(0.0, float(config.get("FOLLOWUP_SECONDS", "10")))
    except ValueError:
        return 10.0


def media_playing():
    """Music or video is audible: Jarvis's own player, or any media player the system reports as playing."""
    if mpvctl.playing():
        return True
    try:
        return platform.media_status() == "Playing"
    except platform.Unsupported:
        return False


class Ears:
    def __init__(self, on_command):
        """on_command(text, via_wake) runs for each command; return True if you expect a reply."""
        self.on_command = on_command
        self.q = queue.Queue(maxsize=400)
        self.noise = collections.deque(maxlen=600)
        self.pre = collections.deque(maxlen=3)
        self._init_echo()
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
        self.followup = followup_seconds()
        self.last_talk = state.read()["talk_request"]
        try:
            self.wake_thr = float(config.get("WAKE_THRESHOLD", "0.4"))
        except ValueError:
            self.wake_thr = 0.4
        self.barge_thr = barge_threshold(self.wake_thr)
        self.debug = config.get("WAKE_DEBUG", "").lower() in ("1", "true", "yes", "on")
        self.debug_at = 0.0
        self.zi = np.zeros(1)
        try:
            self.gain = float(config.get("MIC_GAIN", "4"))
        except ValueError:
            self.gain = 4.0
        self.oww = self._load_wake()
        self.chime = make_chime()

    def _init_echo(self):
        self.roll = collections.deque(maxlen=ROLL_BLOCKS)
        self.gate = echo.EchoGate()
        self.barge_rec = False
        self._media, self._media_at = False, 0.0

    def _load_wake(self):
        import onnxruntime
        from openwakeword.model import Model
        files = config.wake_files()
        if not files:
            raise SystemExit("No wake word model in " + str(config.MODELS))
        real = onnxruntime.InferenceSession

        def cpu_session(*a, **kw):
            kw["providers"] = ["CPUExecutionProvider"]
            return real(*a, **kw)
        onnxruntime.InferenceSession = cpu_session
        try:
            return Model(wakeword_model_paths=[str(p) for p in files])
        finally:
            onnxruntime.InferenceSession = real

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
        self.roll.clear()
        self.barge_rec = False
        self.loud = 0
        self.quiet = 0

    def _begin(self, now, phase, preroll=None):
        state.update(touched_at=time.time())
        mpvctl.duck()
        self.phase = phase
        self.t0 = now
        self.buf = list(preroll or [])
        self.loud = 0
        self.quiet = 0
        self.chimed = False

    def _after(self, seconds):
        """Open the window where the next command needs no wake word. Playback keeps it shut."""
        time.sleep(0.3)
        self._drain()
        self._reset_wake()
        if seconds <= 0:
            self.awake_until = 0.0
        elif mpvctl.ducked() or mpvctl.playing():
            mpvctl.duck()
            self.awake_until = time.time() + seconds
        else:
            self.awake_until = 0.0 if media_playing() else time.time() + seconds

    def run(self):
        stt.warm()
        stream = sd.InputStream(samplerate=SR, channels=1, dtype="int16",
                                blocksize=BLOCK, callback=self._callback)
        stream.start()
        where = "Groq" if stt.CLOUD else "this laptop"
        print(f"  listening for {config.wake_label().title()} (threshold {self.wake_thr}); "
              f"speech is transcribed on {where}. Ctrl+C to stop.")
        print(f"  speech can be cut off by: the wake word while talking (threshold {self.barge_thr:.2f}), "
              "the spoken words stop / quiet / enough, the STOP button or Ctrl+. in the window, "
              "or python -m jarvis.voice.voice --stop")
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
        if st["paused"] or st["dictating"]:
            self._drain()
            self._reset()
            return
        output = voice.SPEAKING.is_set() or (self.phase is None and self._media_now(now))
        if self.gate.feed(block_rms(block), output and self.phase is None, now) and self.phase is None:
            self._barge(block, now)
            return
        if voice.SPEAKING.is_set() and self.phase is None:
            self._interrupt(block, now)
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

    def _media_now(self, now):
        """media_playing() runs a subprocess, so it is asked at most once a second."""
        if now - self._media_at > 1.0:
            self._media_at, self._media = now, media_playing()
        return self._media

    def _barge(self, block, now):
        """The user is talking over Jarvis or the music. Record it, but only a stop word will be acted on (see _handle)."""
        print("  (voice over the output, listening for a stop word)")
        self.barge_rec = True
        self._begin(now, "record", list(self.roll)[-4:] + [block])

    def _interrupt(self, block, now):
        """While Jarvis talks only the wake word, at a higher threshold, can cut in ("Hey Jarvis, stop")."""
        scores = self.oww.predict(block)
        score = max(scores.values()) if scores else 0.0
        if score > self.barge_thr and now > self.cool_until:
            self.cool_until = now + 1.5
            print(f"  (speech cut off by the wake word, score {score:.2f})")
            voice.stop()
            self._drain()
            self._reset_wake()
            self.via_wake = True
            self._begin(now, "wait")

    def _idle(self, block, rms, now):
        self.noise.append(rms)
        self.pre.append(block)
        self.roll.append(block)
        self.n += 1
        if self.n % 25 == 0 and len(self.noise) >= 50:
            floor = float(np.percentile(self.noise, 10))
            self.thr = min(0.25, max(0.015, 3.0 * floor))
            if not self.reported:
                self.reported = True
                print(f"  background {floor:.3f}, speech threshold {self.thr:.3f}")
                if floor > 0.05:
                    print("  the background is loud; lowering the microphone helps: "
                          "lower the input volume in your sound settings")
        if mpvctl.ducked() and now >= self.awake_until:
            mpvctl.unduck()
        scores = self.oww.predict(block)
        score = max(scores.values()) if scores else 0.0
        if self.debug and score > 0.15 and now - self.debug_at > 0.4:
            self.debug_at = now
            print(f"  wake score {score:.2f} (threshold {self.wake_thr})")
        if score > self.wake_thr and now > self.cool_until:
            self.cool_until = now + 1.5
            print(f"  wake (score {score:.2f})")
            events.emit("sys", "wake word heard")
            self.via_wake = True
            before = take_preroll(self.roll, self.thr)
            if before:
                print("  (speech before the wake word is kept)")
                self._begin(now, "record", before)
            else:
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
        if self.quiet >= 10 or len(self.buf) >= (30 if self.barge_rec else 150):
            audio = np.concatenate(self.buf).astype(np.float32) / 32768.0
            via, barge = self.via_wake, self.barge_rec
            self._reset()
            if len(audio) >= int(0.5 * SR):
                try:
                    self._handle(audio, via, barge)
                except Exception:
                    traceback.print_exc()
                    voice.say("Something broke on my side, but I am still here.")
            self._drain()
            self._reset_wake()

    def _handle(self, audio, via_wake, barge=False):
        t0 = time.time()
        raw = stt.transcribe(audio)
        t1 = time.time()
        text = drop_name(strip_wake(raw))
        bare = re.sub(r"[^\w ]", "", text.lower()).strip()
        if barge:
            if echo.is_stop_phrase(text):
                print(f"heard: {repr(text)}")
                events.emit("you", text)
                self.on_command(text, True)
            else:
                print(f"  (ignored while Jarvis was talking: {redact.mask(repr(text))})")
            return
        named = named_anywhere(raw) or any(is_name(w) or is_wake_word(w, 0.7) for w in raw.split()[:3])
        if not bare:
            if via_wake or named:
                print("  (nothing after the wake word)")
                voice.say(random.choice(["Yes?", "I am here.", "Go ahead."]))
                voice.wait()
                self.expect = True
                self._after(max(self.followup, 10))
            else:
                print(f"  (ignored: {repr(raw)})")
            return
        if re.fullmatch(OPENER, bare):
            print("  (waiting for the rest of the sentence)")
            self.expect = True
            self._after(max(self.followup, 10))
            return
        if END.match(bare) and reminders.active() is None:
            print("  (conversation closed)")
            events.emit("you", text)
            voice.say(random.choice(["Anytime.", "Okay.", "Alright."]))
            voice.wait()
            self.expect = False
            self._after(0)
            return
        if not self.expect:
            if is_noise(text):
                print(f"  (ignored: {repr(text)})")
                return
            if not via_wake and len(bare.split()) < 3 and bare.split()[0] not in VERBS:
                print(f"  (ignored a short remark: {repr(text)})")
                return
        print(f"heard: {redact.mask(repr(text))}")
        events.emit("you", text)
        t2 = time.time()
        self.expect = bool(self.on_command(text, via_wake or named))
        print(f"  [speech to text {t1 - t0:.1f}s, thinking and acting {time.time() - t2:.1f}s]")
        voice.wait()
        asked = voice.LAST[0].strip().endswith("?")
        self._after(max(self.followup, 20) if (self.expect or asked) else self.followup)


def _demo(text, via_wake):
    voice.say("I heard: " + text)
    return False


if __name__ == "__main__":
    state.update(paused=False)
    voice.say("Ears test. Say Hey Jarvis, then a short sentence.")
    voice.wait()
    Ears(_demo).run()
