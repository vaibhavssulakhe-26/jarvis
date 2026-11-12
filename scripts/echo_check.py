"""Wake word anywhere in the sentence, echo gating and redaction, with fake audio and fake text. Run: python scripts/echo_check.py"""
import json
import os
import sys
import tempfile
from pathlib import Path

tmp = tempfile.mkdtemp()
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np  # noqa: E402

from jarvis import redact, traces  # noqa: E402
from jarvis.voice import echo, ears  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}" if detail and not ok else ""))
    if not ok:
        bad.append(name)


def blk(level):
    return (np.ones(1280) * level * 32767).astype(np.int16) * np.tile([1, -1], 640).astype(np.int16)


# wake word anywhere
check("the name is dropped from the end", ears.drop_name("play something Jarvis") == "play something")
check("and the middle", ears.drop_name("play Jarvis something") == "play something")
check("'service' stays unless leading", ears.drop_name("restart the service now") == "restart the service now")
check("named anywhere", ears.named_anywhere("play something jarvis") and not ears.named_anywhere("play something"))
quiet, loud = blk(0.003), blk(0.2)
roll = [quiet] * 20 + [loud] * 12 + [quiet] * 4 + [loud] * 14
pre = ears.take_preroll(roll, 0.02)
check("speech before the wake word is kept", pre is not None and len(pre) <= len(roll))
check("the kept audio starts just before the first loud block", pre is not None and len(pre) == len(roll) - 20 + 3, len(pre or []))
check("only the wake word means no pre-roll", ears.take_preroll([quiet] * 36 + [loud] * 14, 0.02) is None)

# echo gate
g, hit, t = echo.EchoGate(), [], 0.0
for level in [0.05] * 12 + [0.06] * 6:
    t += 0.08
    hit.append(g.feed(level, True, t))
check("steady echo is ignored", not any(hit))
t2 = [g.feed(0.3, True, t + 0.08 * (i + 1)) for i in range(4)]
check("a clearly louder voice over the output is noticed", any(t2), t2)
g = echo.EchoGate()
for i in range(8):
    g.feed(0.05, True, i * 0.08)
g.feed(0.0, False, 1.0)
check("the tail right after the output stops is ignored", not any(g.feed(0.5, True, 1.1 + i * 0.08) for i in range(3)))
check("stop words are recognised", all(echo.is_stop_phrase(p) for p in ("stop", "Stop it!", "quiet", "enough", "pause the music", "Jarvis stop")))
check("other speech is not a stop word", not echo.is_stop_phrase("play something louder") and not echo.is_stop_phrase("stop the world please"))

# redaction
cases = {
    "mail me at priya.rao@example.com tomorrow": "mail me at [email] tomorrow",
    "call +91 98765 43210 now": "call [number] now",
    "my card is 4111111111111111": "my card is [number]",
    "the key is gsk_abcdEFGH1234567890xyz": "the key is [key]",
    "my password is hunter2": "my password is [secret]",
    "token: AKIAIOSFODNN7EXAMPLE": "token: [secret]",
    "remind me at 2026-11-12 15:30 about room 204": "remind me at 2026-11-12 15:30 about room 204",
    "secret abcdef0123456789abcdef0123456789abcdef": "secret [secret]",
}
for text, want in cases.items():
    got = redact.mask(text)
    check(f"mask: {text[:36]!r}", got == want, got)
traces.begin("email me at joe@example.org my pin is 4821")
traces.fail("could not reach joe@example.org")
traces.end()
raw = (Path(tmp) / "traces.jsonl").read_text()
row = json.loads(raw.splitlines()[-1])
check("traces never hold the raw text", "joe@example.org" not in raw and "4821" not in raw and "[email]" in row["heard"], raw)
from jarvis.memory import notes  # noqa: E402
notes.save("test", "wifi password is swordfish and call 9876543210", with_window=False)
import sqlite3  # noqa: E402
saved = sqlite3.connect(Path(tmp) / "memory.db").execute("select text from notes").fetchone()[0]
check("notes are masked before saving", "swordfish" not in saved and "9876543210" not in saved, saved)
sys.exit(1 if bad else 0)
