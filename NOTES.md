# Notes on the latest work

## Built
- Phase 1: mpv cleanup on exit, direct stop and pause words, no wake-less recording during playback, stop key kills mpv,
  `USER_NICKNAME`, one announcement and a 60 second offline stretch when both clouds return 429.
- Phase 2: notes and PDF search (`memory/rag.py`, `actions/rag_tools.py`).
- Phase 3: study buddy (`actions/study.py`).
- Phase 4: pomodoro, good morning, quick notes (`scheduling/pomodoro.py`, `actions/focus_tools.py`).
- Phase 5: screen OCR (`screen.read_screen`) and the dictation key (`voice/dictate.py`).
- Phase 6: `scripts/eval_phrases.py`, usage counts, "jarvis stats".
- Phase 8: coding agent loop, background run and stop, fix, add feature, explain, git init (`actions/coder.py`, `actions/procs.py`).
- Phase 9: browser control (`actions/browser.py`).
- Phase 7: README, `.env.example`, CLAUDE.md, this file.

- Phase 10: the dashboard (`ui/dashboard/`), `scripts/dashboard_check.py`.

## Skipped
Nothing was skipped. Parts that could not be fully exercised here:
- OCR with a real tesseract: not installed on this laptop (`sudo dnf install tesseract`). The tool and its error path are tested with fakes.
- Dictation with the real key: you are not in the `input` group, so the key listener cannot read the keyboard. The recording, paste and
  `--once` shortcut mode are tested with fakes.
- A live screenshot (`SCREEN_LIVE=1 python scripts/screen_check.py`).

## Decisions and limits worth knowing
- "stop" with no wake word: the mic is not sent to speech recognition while music plays, so a bare "stop" cannot be heard. Say the wake word
  first ("Alexa, stop"), or use the STOP button, Ctrl+. or `python -m jarvis.voice.voice --stop`. Typed or palette commands work as is.
- Generated code is not sandboxed by the operating system. It runs in the project folder with a reduced environment (no API keys), and anything
  containing sudo, rm -rf and similar is never written or run, but a program could still touch files outside the workspace.
- `build_project` runs inside the normal command handler, so a spoken "stop" cannot interrupt it while it works.
- A build that needs packages (Flask, FastAPI) stops and asks first. The answer "yes" creates `<project>/.venv` and installs the names in
  `requirements.txt`, nothing else (no options, URLs or paths).
- "open <domain>" and "search X on Google/YouTube/GitHub" use the Playwright browser only when Playwright and a browser are ready.
  "open youtube" (no dot) still opens the YouTube app alias as before.
- Browser downloads are cancelled when a page starts them; a yes fetches the file again into `~/Downloads` (or `BROWSER_DOWNLOADS`).
- `scripts/memory_check.py` has a timing race ("turn cap removes oldest summarised rows"): it failed twice in a row once and passes on
  the original code and on reruns. Not changed.
- `python -m jarvis.main --text` sometimes segfaults while exiting after a chat call (it does the same on the original code, so it is
  not from this work; it looks like the exit-time summary racing the voice thread). Everything has run and been saved by then.
- `scripts/brain_check.py` now uses a scratch data folder, because routing now counts requests in `data/usage.json`.
- Playwright was added to `requirements.txt` and installed in `.venv`.

## Needs a real microphone to verify
- "Alexa, stop" and "Alexa, pause" while a song plays; then silence for a minute with music on: no transcripts should appear.
- The follow-up window after a normal reply, and that music in the room does not start a recording.
- Quiz answers spoken aloud ("quiz me on trees", then your answer), the check-in questions ("log today": a time, yes or no, minutes).
- "Vib" as the spoken nickname: set `USER_NICKNAME=Vib` and listen to how Piper says it; add a line to `PRONOUNCE` in `voice/voice.py` if it is off.
- Dictation: set `DICTATE_KEY`, join the input group, hold the key and speak; or bind `--once` to a KDE shortcut.
- "start focus 1": the spoken start and the spoken end after a minute.
- Browser: risky click and download questions answered by voice ("yes", "no").

## Dashboard
- Measured offscreen: about 123 MB for the whole process with the window open, an orb frame paints in about 4 ms, and the animation uses about
  26% of one core at 30 fps (11% in low power). On a real display only the dirty region is repainted, so expect less. Not measured on your screen.
- The speaking ripples follow the real loudness of each spoken line (read from the audio file), not a fake wave.
- The old window (`python -m jarvis.ui.ui`) is still there and unchanged apart from sharing `shutdown_all`.
- Needs your eyes: how the orb and panels look at your resolution, the tray icon on Plasma, smoothness of the colour fade, and that closing
  to the tray and then "Quit" from the tray leaves no mpv, Chrome or project processes running.

## Phase 11
- The confirmation phrases in `scripts/confirm_check.py` and `route_check.py` are my best reconstruction (I did not have your log text), so add the
  exact sentences from the log to those two scripts if any of them still misbehaves.
- "update your notes" maps to the existing `append_to_note` tool (there is no `append_note`).
- `scripts/reminders_check.py` has a time-of-day dependency ("third snooze returns a suggested time") and fails in the afternoon; it does not touch
  anything changed here.
- Previews: `data/ui-previews/home-<theme>.png`, rendered offscreen at 1280 by 760.
