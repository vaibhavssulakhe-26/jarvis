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

- Phase 12: browser keeps its sandbox and always loads its target, live answers without a browser (`research/live.py`), `BRAIN=hybrid|offline`, real
  purple/pink/red themes, one state for Now Playing and the queue, RAG_FOLDERS in the Notes page, Study behind `STUDY=on`, faster two-sentence streaming voice.
- Phase 13: routines (`data/routines.md`), morning briefing with one brain call or a template, read-only iCal calendar, systemd timer, email-safe reply drafts,
  voice commands, Home card.
- Phase 14: `jarvis.doctor` and the Settings card, offline model by free memory, request traces with "show my failures" and `scripts/replay_failures.py`,
  `jarvis.bench` and the Stats card. New checks: `live_check`, `routines_check`, `doctor_check`, `traces_check`.

- Phase 14b: wake word anywhere in the sentence, echo gate for barge-in by stop words, redaction of stored text.
- Phase 15: `jarvis/platform/` (Linux and Mac backends), setup wizard and `scripts/install.sh`, profiles, `scripts/platform_check.py`, GitHub Actions on Ubuntu and macOS.
- Phase 16: job helper (`jobs/`, `actions/job_tools.py`, Jobs page, `scripts/jobs_check.py`).

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

## Phases 12 to 14: what could not be verified here
Everything below passes with fakes; none of it has met your real accounts or hardware.
- Real mailbox: IMAP login with your app password, the unread count, `BODY.PEEK` fetching and that "draft a reply to <sender>" really lands in Gmail
  Drafts (the folder name `[Gmail]/Drafts` assumes an English Gmail; other languages name it differently).
- Real calendar: put the secret iCal address in `CALENDAR_ICS_URL` and say "what's on my calendar". Only simple repeat rules are expanded (daily, weekly with
  BYDAY, monthly, yearly, COUNT, UNTIL, EXDATE). Edited single occurrences (RECURRENCE-ID) are not applied.
- systemd: copy the two files from `systemd/` to `~/.config/systemd/user/` and enable the timer (see README). I did not install or start it.
- Live answers: DuckDuckGo's HTML page can change or show a captcha; then Jarvis says it could not get results. Not tried against the real site.
- Voice: the quality of the best-voice pick, `length_scale` 0.92 and the sentence-by-sentence overlap need your ears. The installed voices are all medium, so
  `best()` falls back to the default Ryan voice among equals.
- Doctor: the microphone level uses the live mic level when the app runs, otherwise a 0.4 second recording.
- `python -m jarvis.bench --live` spends tokens and was not run; the default mock run is what the checks cover.
- The dashboard changes were checked offscreen only: look at the purple, pink and red themes, the Home briefing card, the Notes counter, the Doctor card.
- Traces mark a request "corrected" by heuristics (a repeat of three or more words, or a sentence starting "no", "I said", "I meant"). Expect an occasional
  false mark; "show my failures" is a hint, not proof.
- `scripts/screen_check.py` failed once during a long run while files were being edited and passed on its own; likely a timing flake.

## Phases 14b to 16: what could not be verified here
- The Mac backend and the macOS CI job have never run on a Mac; the GitHub workflow itself has not been run at all (no network push from here). It lists only checks
  that passed locally on Linux, and marks the ones that use sockets, evdev-style input or Qt windows as `linux`.
- Echo gate and wake-before-name need your room and microphone: tune with `WAKE_DEBUG=1`. The gate thresholds (1.8 times the learned echo, 0.03 minimum) are guesses.
- `python -m jarvis.setup` was tested with fakes only (venv creation, voice download and key prompts are mocked); try it once on a fresh clone.
- Jobs: resume types BA, DA, OA, PA are read as business, data, operations and product analyst. The skill list in `jobs/analyse.py` is a plain vocabulary, so
  unusual skills are not noticed. Interview feedback quality depends on the brain; the offline feedback is only a heuristic.
- A profile's `.env.<name>` is read before `.env`, so keys in the shared `.env` are shared by every profile. Put a person's own keys in their file.

## Phase 17: line counts before slimming

| package | lines |
|---|---|
| actions | 6013 |
| brain | 665 |
| core | 1029 |
| jobs | 577 |
| memory | 724 |
| platform | 756 |
| research | 497 |
| routines | 630 |
| scheduling | 1298 |
| ui | 2684 |
| voice | 1314 |
| top-level modules | 769 |
| scripts | 6744 |
| total jarvis/ | 16956 |

## Phase 17: line counts after slimming

| package | lines |
|---|---|
| actions | 5983 |
| brain | 665 |
| core | 1036 |
| jobs | 553 |
| memory | 724 |
| platform | 756 |
| research | 497 |
| routines | 625 |
| scheduling | 1280 |
| ui | 2667 |
| voice | 1313 |
| top-level modules | 783 |
| scripts | 6747 |
| total jarvis/ | 16882 |

Slimming was small on purpose (about 100 lines in `jarvis/`; the package grew by about 3,500 lines during phases 14b to 16 before it). What changed:
- Unused imports removed with `ruff check --select F401,F841` in `jarvis/` and `scripts/` (the Linux-only command imports that moved into `platform/` account for most).
- Dead code removed after checking each hit by hand: `coder.top_module`, `tracker.applied_since`, `reminders.take_due`, `config.OTHER_NAMES` (and `USER_OTHER_NAMES` in
  `.env.example`), `Theme.version`. Everything vulture still lists is a Qt callback signature, a tool registered by decorator, an attribute kept alive on purpose, or is used
  by a check script (`config.NICKNAME`, `Companion.touch`).
- Duplicate JSON load and save code (study, reminders, state, voice settings and theme settings, usage and eval stats, bench, routines state, jobs, interview log,
  contacts) now goes through `jarvis/core/jsonfile.py`. Voice and theme settings share `voices.read_settings` and `voices.write_settings`.
- No stale TODOs, commented-out code, debug prints or unused `.env` keys were found. No files were deleted: every module is imported or documented, and `scripts/mic_check.py`
  and `scripts/make_icon.py` are documented tools. Long `if` chains such as `main.fast_path` were left as they are, since a table would not be simpler.
- The git tag `pre-slim` points at a snapshot commit of the working tree taken just before slimming (the tree was not committed to any branch; HEAD and the branch are
  unchanged). `git diff pre-slim` shows what slimming changed. Delete it with `git tag -d pre-slim` when you no longer need it.
