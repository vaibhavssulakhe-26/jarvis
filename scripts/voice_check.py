"""Lists the installed voices and speaks one short line per voice. Run: python scripts/voice_check.py [--quiet]"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ["JARVIS_DATA"] = tempfile.mkdtemp(prefix="jarvis-voice-")

from jarvis.actions import tools  # noqa: E402,F401
from jarvis.voice import voice, voices  # noqa: E402

names = voices.english()
print("installed voices:")
for n in names:
    print(f"  {n}  ({voices.label(n)})")
bad = 0
if not names:
    print("no voices found in models/voices or ~/piper-voices")
    sys.exit(1)
print("default now:", voices.current_name())
for n in names:
    voices.choose(n)
    ok = voices.current_name() == n
    bad += not ok
    print(("ok   " if ok else "FAIL ") + "switched to " + n)
    if "--quiet" not in sys.argv:
        voice.say(f"Hello, this is {voices.label(n)}.")
        voice.wait()
run = tools.TOOLS["change_voice"]["fn"]
for want in ("male", "female", "british", "next"):
    out = run({"which": want})
    print("ok   " + want + " -> " + voices.current_name())
sys.exit(1 if bad else 0)
