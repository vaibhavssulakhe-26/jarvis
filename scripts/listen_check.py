"""Speech detection, end of speech, crowd mode and push to talk with synthetic audio. Run: python scripts/listen_check.py"""
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402

from jarvis.voice import ears, listen, ptt, vad  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


rng = np.random.default_rng(1)
SR = 16000


def noise(seconds, level):
    return (rng.normal(0, level, int(SR * seconds)) * 32767).astype(np.int16)


def speechlike(seconds, level=0.25):
    """Voiced-sounding signal: a 120 Hz buzz with harmonics and a syllable-rate envelope."""
    t = np.arange(int(SR * seconds)) / SR
    wave = sum(np.sin(2 * np.pi * 120 * k * t) / k for k in range(1, 12))
    env = 0.5 + 0.5 * np.sin(2 * np.pi * 4 * t) ** 2
    return (level * wave * env / 3 * 32767).astype(np.int16)


def blocks(x):
    return [x[i:i + 1280] for i in range(0, len(x) - 1279, 1280)]


# endpointer
ep = vad.Endpointer(silence=0.8, cap=12)
got = [ep.feed(True) for _ in range(20)] + [ep.feed(False) for _ in range(12)]
check("ends after 0.8 s of silence", got.index("silence") == 20 + 9, str(got.index("silence") if "silence" in got else None))
ep = vad.Endpointer(silence=0.8, cap=2)
res = [ep.feed(True) for _ in range(40)]
check("cap ends a recording that never stops", "cap" in res and res.index("cap") == 24, str(res.index("cap") if "cap" in res else None))
ep = vad.Endpointer(silence=0.8, cap=12)
res = [ep.feed(i % 8 != 0) for i in range(100)]
check("short pauses do not end it", "silence" not in res[:60])

# detector, whatever backend loaded
det = vad.Detector()
print("  backend:", det.backend)
check("a backend loaded", det.backend in ("silero", "webrtc", "energy"))
quiet = blocks(noise(1.0, 0.004))
check("room noise is not speech", sum(det.is_speech(b, ears.block_rms(b), 0.02) for b in quiet) <= len(quiet) * 0.2)
det.reset()
loud = blocks(noise(1.0, 0.2))
check("steady loud noise in crowd mode is mostly rejected or gated", sum(det.is_speech(b, ears.block_rms(b), 0.5, True) for b in loud) <= len(loud) * 0.5)
det.reset()
voiced = blocks(speechlike(1.5))
check("loudness fallback hears a loud voice", vad.Detector("none").is_speech(voiced[3], ears.block_rms(voiced[3]), 0.02))

# thresholds learned from the floor
check("crowd threshold is higher", listen.speech_threshold(0.02, True) > listen.speech_threshold(0.02, False))
check("threshold has a floor", listen.speech_threshold(0.0, False) >= 0.015 and listen.speech_threshold(0.0, True) >= 0.03)

# crowd switch persists
listen.set_crowd(True)
check("crowd mode on", listen.crowd())
listen.set_crowd(False)
check("crowd mode off", not listen.crowd())

# denoise keeps length and lowers steady noise
mix = (speechlike(2.0, 0.2).astype(np.float32) + noise(2.0, 0.05).astype(np.float32)) / 32768
out = vad.denoise(mix.astype(np.float32))
tail_in, tail_out = float(np.std(mix[:1000])), float(np.std(out[:1000]))
check("denoise keeps the length", len(out) == len(mix))
check("denoise lowers steady noise", np.isfinite(out).all() and tail_out <= tail_in + 1e-6, f"{tail_in:.4f} {tail_out:.4f}")

# ears behaviour with a fake wake model and no microphone
class Fake:
    def predict(self, block):
        return {"w": 0.0}


def make_ears(heard):
    ears.Ears._load_wake = lambda self: Fake()
    e = ears.Ears(lambda text, via: heard.append((text, via)) or False)
    e._after = lambda s: None
    return e


heard = []
e = make_ears(heard)
seen = []
ears.stt.transcribe = lambda audio: seen.append(len(audio)) or "open the browser"
ears.voice.wait = lambda: None
ears.voice.say = lambda *a, **k: None
ears.voice.LAST[0] = ""

# push to talk: held, spoken, released
ptt.press()
for b in blocks(speechlike(1.2)):
    e._step(b)
check("hold starts a push to talk recording", e.phase == "ptt")
ptt.release()
e._step(blocks(noise(0.2, 0.003))[0])
check("release sends it and returns to idle", e.phase is None and seen and heard and heard[0][1] is True, f"{e.phase} {seen} {heard}")

# a tap is left to the Talk button's click
heard.clear()
ptt.press()
e._step(blocks(noise(0.2, 0.003))[0])
ptt.release()
e._step(blocks(noise(0.2, 0.003))[0])
check("a quick tap records nothing", e.phase is None, str(e.phase))
e._reset()

# the cap ends a held key too
seen.clear()
os.environ["MAX_RECORD_SECONDS"] = "2"
ptt.press()
steps = 0
for b in blocks(speechlike(4.0)):
    e._step(b)
    steps += 1
    if e.phase is None:
        break
ptt.release()
check("a held key is cut at the cap and returns to idle", e.phase is None and seen and steps <= 27, f"{steps} {e.phase}")
os.environ.pop("MAX_RECORD_SECONDS")

# normal recording ends on silence and returns to idle
seen.clear()
heard.clear()
e._begin(1.0, "record")
e.thr = 0.02
for b in blocks(speechlike(1.0)) + blocks(noise(1.5, 0.002)):
    e._recording(b, ears.block_rms(b), 1.0)
    if e.phase is None:
        break
check("a command ends after the pause and goes idle", e.phase is None and seen, f"{e.phase}")

# crowd mode: no wake word, no command
heard.clear()
listen.set_crowd(True)
e._handle(np.zeros(16000, dtype=np.float32), False)
check("crowd mode ignores speech without the wake word", not heard)
e._handle(np.zeros(16000, dtype=np.float32), True)
check("crowd mode accepts it after the wake word", len(heard) == 1)
listen.set_crowd(False)

print("\n%d failed" % len(bad) if bad else "\nall passed")
sys.exit(1 if bad else 0)
