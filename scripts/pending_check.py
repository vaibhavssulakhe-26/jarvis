"""Checks the pending file choice and the yes/no handler without a mic or network."""
import sys
import time
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from jarvis.actions import files
from jarvis.core import main

said = []
fails = 0


def check(name, ok):
    global fails
    fails += 0 if ok else 1
    print(("ok   " if ok else "FAIL ") + name)


now = time.time()
opts = [{"path": Path(f"/tmp/f{i}.pdf"), "modified": now - i * 100, "score": 1.0} for i in range(3)]
files.PENDING.clear()
files.PENDING.update({"options": opts, "then": ("summarise_file", {}), "until": now + 60})
for phrase, want in [("second", 1), ("the second one", 1), ("second one, second one", 1), ("A. Jarvis, the second one", 1),
                     ("number two", 1), ("2", 1), ("first", 0), ("the newest", 0), ("the oldest", 2), ("last one", 2)]:
    got = files.pick(phrase)
    check(f"pick {phrase!r}", got is opts[want])
check("garbled keeps pending", files.hold_choice("uh hmm the") is not None and files.waiting())
check("repeat keeps pending", "options" in (files.hold_choice("say that again") or "options") and files.waiting())
check("new request passes through", files.hold_choice("find my resume in downloads please now") is None)

ran = []
with mock.patch.object(main.voice, "say", side_effect=said.append), \
        mock.patch.object(main, "do_tool", side_effect=lambda a, b, s="": ran.append(a)), \
        mock.patch.object(main, "_handle", side_effect=lambda t, v=True: ran.append("new:" + t)):
    def ask(reply):
        ran.clear()
        main.PENDING.clear()
        main.PENDING.update({"action": "take_note", "args": {}, "until": time.time() + 60})
        handled = main.check_pending(reply)
        return handled, list(ran), bool(main.PENDING)

    check("yes", ask("yes") == (True, ["take_note"], False))
    check("yes yes yes", ask("yes yes yes") == (True, ["take_note"], False))
    check("yeah sure", ask("yeah sure") == (True, ["take_note"], False))
    check("no", ask("no")[1] == [] and not main.PENDING)
    check("don't", ask("don't")[1] == [])
    h = ask("yes, save this as a note and open downloads")
    check("yes with extra", h[1][0] == "take_note" and h[1][1].startswith("new:open downloads"))
    check("unrelated cancels", ask("what time is it")[:2] == (False, []))
print("failures:", fails)
sys.exit(1 if fails else 0)
