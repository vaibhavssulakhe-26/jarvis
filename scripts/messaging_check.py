"""WhatsApp sending: never empty or "?", the exact text is in the question, non-ASCII text is pasted from the clipboard (never typed), and the spoken
result never claims delivery. Hindi and Kannada included. No browser, keyboard or clipboard is touched. Run: python scripts/messaging_check.py"""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

tmp = tempfile.mkdtemp(prefix="jarvis-msg-")
os.environ["JARVIS_DATA"] = tmp
os.environ["XDG_RUNTIME_DIR"] = tmp
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis import platform  # noqa: E402
from jarvis.actions import messaging, tools  # noqa: E402
from jarvis.brain import brain  # noqa: E402
from jarvis.voice import voice  # noqa: E402

bad = []


def check(name, ok, detail=""):
    print(("ok   " if ok else "FAIL ") + name + (f"  {detail}"[:240] if detail and not ok else ""))
    if not ok:
        bad.append(name)


messaging.CONTACTS = Path(tmp) / "contacts.json"
messaging.CONTACTS.write_text(json.dumps({"mom": {"phone": "919800000000"}}), encoding="utf-8")
events = []
clip = []
opened = []
said, later = [], []
patches = [
    mock.patch.object(platform, "clipboard_write", lambda t: clip.append(t) or events.append("copy") or True),
    mock.patch.object(platform, "send_paste", lambda terminal=False: events.append("paste")),
    mock.patch.object(platform, "send_enter", lambda: events.append("enter")),
    mock.patch.object(messaging, "_browser", lambda url: opened.append(url)),
    mock.patch.object(messaging, "_send_later", lambda *a: later.append(a)),
    mock.patch.object(messaging.time, "sleep", lambda s: None),
    mock.patch.object(voice, "say", lambda t, *a, **k: said.append(str(t))),
]
for p in patches:
    p.start()
brain.RECENT[:] = ["message mom I will be home by eight"]

# empty text and bare punctuation are refused, by the question and by the tool
for text in ("", "   ", "?", "??", "...", "!?", None):
    try:
        messaging._describe_message({"contact": "mom", "text": text})
        asked = True
    except tools.ToolError:
        asked = False
    try:
        messaging.message_contact({"contact": "mom", "text": text, "_checked": True})
        sent = True
    except tools.ToolError:
        sent = False
    check(f"{text!r} is neither asked about nor sent", not asked and not sent)
check("nothing was opened for them", not opened and not events)

# the exact text is in the confirmation
for text in ("I will be home by eight", "मैं आठ बजे तक घर आऊँगा", "ನಾನು ಎಂಟು ಗಂಟೆಗೆ ಮನೆಗೆ ಬರುತ್ತೇನೆ"):
    q = messaging._describe_message({"contact": "mom", "text": text})
    check(f"the question carries the exact text: {text[:12]}", f'"{text}"' in q and "mom" in q, q)

# ascii goes through the address, key presses only press enter
del events[:], opened[:], clip[:], said[:]
out = messaging.message_contact({"contact": "mom", "text": "I will be home by eight", "_checked": True})
line = messaging._deliver(0, "mom", "I will be home by eight", False)
check("the delivery is scheduled with the plain flag", later and later[-1][3] is False, str(later))
check("plain text is placed by the address and only Enter is pressed", "text=I%20will%20be%20home%20by%20eight" in opened[0] and events == ["enter"], f"{opened} {events}")

# hindi and kannada are pasted, never typed
for text in ("मैं आठ बजे तक घर आऊँगा", "ನಾನು ಎಂಟು ಗಂಟೆಗೆ ಮನೆಗೆ ಬರುತ್ತೇನೆ"):
    del events[:], opened[:], clip[:], said[:]
    out = messaging.message_contact({"contact": "mom", "text": text, "_checked": True})
    check(f"{text[:8]}: delivery is scheduled as a paste", later and later[-1][3] is True and later[-1][2] == text, str(later))
    check(f"{text[:8]}: the address has no text and no non-ASCII reaches a URL", "text=" not in opened[0] and opened[0].isascii(), opened)
    check(f"{text[:8]}: the text is put on the clipboard unchanged", clip and clip[0] == text, str(clip))
    del events[:], clip[:]
    line = messaging._deliver(0, "mom", text, True)
    check(f"{text[:8]}: copy, then paste, then Enter, in that order", events == ["copy", "paste", "enter"], str(events))
    check(f"{text[:8]}: the clipboard held exactly the text", clip == [text], str(clip))
    check(f"{text[:8]}: the result does not claim delivery", "cannot verify" in line and "sent it" not in line.lower() and "was sent" not in line.lower(), line)
check("the first reply does not claim it was sent", "cannot check" in out and "I sent" not in out and "has been sent" not in out, out)

# no clipboard tool: refuse before opening anything, say so
del events[:], opened[:], said[:]
with mock.patch.object(platform, "clipboard_write", lambda t: False):
    try:
        messaging.message_contact({"contact": "mom", "text": "ನಮಸ್ಕಾರ", "_checked": True})
        refused = ""
    except tools.ToolError as e:
        refused = str(e)
check("without a clipboard tool a Kannada message is refused, not typed", "did not send" in refused and not opened and not events, f"{refused} {opened} {events}")
with mock.patch.object(platform, "clipboard_write", lambda t: False):
    line = messaging._deliver(0, "mom", "ನಮಸ್ಕಾರ", True)
check("a clipboard that fails later presses nothing and says nothing was sent", events == [] and "did not send" in line, f"{events} {line}")

# a key press that fails is reported plainly
def broken():
    raise OSError("no uinput")


with mock.patch.object(platform, "send_enter", broken):
    line = messaging._deliver(0, "mom", "hello there", False)
check("a failed key press does not claim success", "could not" in line and "check WhatsApp" in line and "went through" not in line, line)

for p in patches:
    p.stop()
print("\n" + ("all passed" if not bad else f"{len(bad)} failed"))
sys.exit(1 if bad else 0)
