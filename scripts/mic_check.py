import subprocess
import time

import numpy as np
import sounddevice as sd

SR = 16000
LEVELS = [0.3, 0.5, 0.8, 1.0]


def wpctl(*args):
    r = subprocess.run(["wpctl", *args], capture_output=True, text=True)
    return r.stdout.strip()


def record(seconds):
    audio = sd.rec(int(seconds * SR), samplerate=SR, channels=1, dtype="float32")
    sd.wait()
    return audio.flatten()


def ac_levels(audio):
    n = SR // 10
    blocks = [audio[i:i + n] for i in range(0, len(audio) - n + 1, n)]
    return np.array([float(np.std(b)) for b in blocks])


start = wpctl("get-volume", "@DEFAULT_AUDIO_SOURCE@")
print("current microphone volume:", start)
wpctl("set-mute", "@DEFAULT_AUDIO_SOURCE@", "0")
input("Press Enter. At each level you stay quiet for 3 seconds, then speak for 4 seconds. ")
rows = []
for v in LEVELS:
    wpctl("set-volume", "@DEFAULT_AUDIO_SOURCE@", str(v))
    time.sleep(0.8)
    print(f"\nlevel {v}: stay QUIET (3 seconds)")
    time.sleep(1.0)
    quiet = record(3.0)
    print(f"level {v}: now SAY 'testing one two three four' (4 seconds)")
    time.sleep(0.3)
    spoken = record(4.0)
    noise = float(np.median(ac_levels(quiet)))
    speech = float(np.percentile(ac_levels(spoken), 90))
    dc = float(np.mean(quiet))
    total = float(np.sqrt(np.mean(quiet ** 2)))
    peak = float(np.abs(spoken).max())
    rows.append((v, dc, total, noise, speech, peak))

print("\nvolume  dc_offset  noise_total  noise_ac  speech_ac  ratio  peak")
best = None
for v, dc, total, noise, speech, peak in rows:
    ratio = speech / max(noise, 0.0001)
    print(f"{v:<7} {dc:+.3f}     {total:.3f}        {noise:.3f}     {speech:.3f}      {ratio:5.1f}  {peak:.2f}")
    if peak < 0.95 and (best is None or ratio > best[1]):
        best = (v, ratio)
if best is None:
    best = (min(r[0] for r in rows), 0.0)
wpctl("set-volume", "@DEFAULT_AUDIO_SOURCE@", str(best[0]))
print(f"\nmicrophone set to {best[0]} (speech is {best[1]:.1f} times louder than the room).")
print("To undo, run wpctl set-volume @DEFAULT_AUDIO_SOURCE@ followed by the old value. The old volume was:", start)
