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

- Phase 22: Telegram bot (`telegram.py`), `scripts/telegram_check.py`.
- Phase 23: timetable, deadlines and the daily brief (`timetable.py`, `actions/planner_tools.py`, `scripts/timetable_check.py`). The old `scripts/schedule_check.py`
  (briefing and page monitor) is unchanged; the new check has its own name.
- Phase 24: email digest (`routines/maildigest.py`, `mail.fetch_recent`, `scripts/digest_check.py`).
- Phase 25: study from notes (`actions/notes_quiz.py`, `scripts/study_notes_check.py`).
- Phase 26: alerts and quick tasks (`alerts.py`, `tasks.py`, `scripts/alerts_check.py`).
- Phase 27: offline Wikipedia (`research/wiki.py`, `scripts/wiki_check.py`).
- Phase 28: web project helper (`actions/webproject.py`, `scripts/webproject_check.py`).

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
- The old holographic window was removed in v4 prep; `jarvis/ui/ui.py` now only holds `start_core` and `shutdown_all` for the dashboard.
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

## Phases 19 to 21

### Phase 19: listening in noise
- `voice/vad.py`: Silero VAD (the model that ships with openwakeword, or `models/silero_vad.onnx`) through onnxruntime, then webrtcvad if installed
  (it is not, here), then a loudness test. `Endpointer` ends a recording after 0.8 s of silence and caps it at `MAX_RECORD_SECONDS` (12); after either,
  `Ears._finish` processes the audio and goes back to idle. `denoise` is the light spectral gate behind `NOISE_SUPPRESS` (off by default).
- `voice/ptt.py`: hold `PTT_KEY` (evdev, needs the input group) or the dashboard Talk button, release to send, no wake word. A tap under 0.5 s is left to
  the button's old click (`talk_request`).
- `voice/listen.py`: crowd mode (`CROWD_MODE`, Settings checkbox, voice "crowd mode on/off"): wake word for every command, no follow-up window, no pre-roll,
  higher threshold from the measured floor, and a model probability of 0.7 instead of 0.5. The saved choice is in `data/settings.json`.
- Doctor has a `listening` line (mode, noise floor, detector, push-to-talk key); the dashboard bottom bar has a mic meter with ticks for the floor and the threshold.
- `scripts/listen_check.py` (synthetic noise and a voiced-sounding signal).

### Phase 20: chat, memory, quality
- `memory/threads.py` (data/chats/<id>.json, redacted), `ui/dashboard/chat.py` (`ChatView`: bubbles, markdown, copy, streaming, list, file drops), the Chat page
  and a collapsible dock on every other page. Typed and spoken lines share one thread through the event bus.
- `brain.generate` is the tier ladder: larger Groq model (`GROQ_STRONG_MODEL`, 40 calls a day, rests a minute after a 429) for hard questions, then the fast
  model, then OpenRouter and Ollama. The tier reaches the feed and the chat bubble through the `tier` event. Quality mode (`QUALITY_MODE`, on) is for chat
  turns only; tool routing keeps its small prompt. `route_check` now measures the chat budget with quality off and has a separate, larger limit for quality on.
- Streaming: `voice/stream.py` speaks the first sentence as soon as it is complete (`voice.speak_part`), `voice.say(skip=, limit=)` speaks the rest (four
  sentences in quality mode); the full text stays in the chat.
- `memory/facts.py` (data/memory.jsonl, SQLite FTS built in memory, top 5 per chat turn), refusing secrets, health words and anything about other people.
  Facts are mined five quiet minutes after a conversation, on "new chat", and at exit (local rules only at exit). "what do you remember about X",
  "show my memory", "forget X"; viewer and per-fact forget button on the Notes page.
- Drop a PDF, text or image on the chat (`actions/attach.py`); secrets are masked, the file goes in as data.
- `scripts/chat_check.py`, and fact tests added to `scripts/memory_check.py`.

### Phase 21: browser agent
- `actions/web_agent.py` (`browse_agent`, "use the browser to ..."): plan once on the strong tier, then up to `AGENT_MAX_STEPS` (12) fast-tier steps, each
  looking at the accessibility tree (`aria_snapshot`) plus visible text. Two failures re-plan (twice at most). Actions reuse the browser tool's own checks.
- Risky clicks, login pages and downloads ask through the normal pending yes/no; a captcha ends the task; typed text may not contain links the goal did not
  contain. Stop: dashboard button, Ctrl+., the word stop, `AGENT_ABORT_KEY` (KEY_PAUSE, needs the input group).
- Web page shows the plan and steps live. `scripts/agent_check.py` runs real headless Chrome against a local site with a scripted model.

### What needs your real mic, speakers or browser
- Push to talk with a real key (`PTT_KEY`, input group) and the Talk button held down; crowd mode in a noisy room; whether 0.8 s feels right; `NOISE_SUPPRESS`.
- Streaming reply: the first sentence starting while the rest arrives; four spoken sentences in quality mode; the larger model on your actual Groq quota
  (`openai/gpt-oss-120b` is the default name; change `GROQ_STRONG_MODEL` if your account lists another).
- Chat look and feel, drops of a real PDF and image, memory extraction with the live model (the check only uses fakes).
- The agent on real sites: confirmations by voice, the abort key, and a real login page. Sites that block automation will hit the captcha stop.

### Decisions and limits
- webrtcvad is not installed; the Silero path was tested. The loudness fallback is tested with synthetic audio only.
- The chat dock and page keep the last 30 and 60 bubbles on screen; the full history is on disk.
- Facts are deliberately conservative: any sentence with he, she, they, a family word, a health word or a number sequence is not stored.
- The agent cannot click things that have no accessible name, and it does not handle iframes or file pickers.

## Phases 22 to 28

### What was built
- Telegram: long polling with requests, six digit pairing, owner only, confirmations, send/delete/power never from the phone, agent tasks behind `TELEGRAM_ALLOW_AGENT`,
  `/brief /email /tasks /status /stop`, notifications for the brief, the email digest, alerts and reminders. Replies are collected with `voice.capture()`.
- Timetable and deadlines (two hand-editable files), quick tasks, the brief with classes, deadlines, tasks, the study set and a focus line, pushed at `BRIEFING_TIME`
  to the dashboard, the voice and Telegram.
- Email digest (rules first, one model call for the unclear ones, injection mail withheld), notes quizzes with Leitner boxes (PDFs work), alerts with a dashboard chip,
  the offline Wikipedia pack, and the website helper (scaffold, accessibility pass, local preview, zip export).

### Decisions
- The digest time is `EMAIL_DIGEST_TIME`, not `DIGEST_TIME`: that name already belongs to the old weather and news digest in `scheduling/digest.py`.
- The new timetable check is `scripts/timetable_check.py`; `scripts/schedule_check.py` already tested the old briefing and page monitor.
- Telegram drops messages that arrived while Jarvis was off, so an old command can never run by surprise.
- "what is X" goes to the offline pack only when `BRAIN=offline` and a pack is ready; "look up X" always uses it.
- The accessibility pass changes only what is safe (lang, viewport, alt text from the file name, skip link, focus style) and keeps a `.bak`; contrast and heading order are only reported.
- Brief budget: the prompt is trimmed to 640 estimated tokens and the answer capped at 150, so the one call stays under 800.

### Known flakes and limits
- `focus_check` failed once at the start of this work (do-not-disturb over D-Bus, `RuntimeError`) and passed on a later run; it depends on the session bus.
- `schedule_check` has a time-of-day dependence: a run that crosses midnight failed "deadline reminder is flagged" and passed after midnight.
- python-libzim is not installed here, so the libzim glue in `research/wiki.py` was tested against a fake module shaped like the documented API, not a real ZIM file.
- Telegram was tested against a fake Bot API on localhost, never against Telegram itself.

### Needs your real phone, mailbox, calendar, mic or browser
- Phone: create the bot with @BotFather, pair, and try the commands from a second account (it must get no reply). Check that the confirmation wording reads well on a small screen
  and that notifications arrive when the app is closed (they do not: only the running app sends them, except the systemd timer, which also sends the brief and digest).
- Mailbox: the digest with your real Gmail (the `SINCE` search and the Date headers of real mail), and how well the rules sort your actual senders.
- Calendar: the brief with `CALENDAR_ICS_URL` next to the timetable.
- Mic: "quiz me from my notes" and "review due questions" by voice, answers spoken at normal speed, the follow-up window staying open between questions.
- Browser: "preview it" in Chrome, a real site made by the coder with your real model (the check uses canned files), and the GitHub Pages and Netlify steps.
- A real ZIM file with `pip install libzim` (title suggestions and full text search differ between files).

### How to test
See "How to test phases 22 to 28" in README.md.

## Phases 30 and 31

### Built
- Agent core (`brain/agent.py`), truthful tool results, self block, outage handling with cause and reset time, "(offline)" prefix, file tools with the deny list, verified hand-off, UTF-8 everywhere,
  filler removed (start-up greeting, jokes, motivational lines, briefing greeting), `scripts/core_check.py` (25 phrases plus extras) with the rate on the Stats page, `scripts/encoding_check.py`.
- Dashboard v3: icon rail, slim top bar and status pill, Home with the orb as a background layer and the chat as the main panel, tool chips, streaming cursor, masking with a reveal switch, separate Chat,
  Activity and Build logs, resizable drawer, Ice default theme with a charcoal grid and scan line layer, five distinct orb states, 4.5 to 1 contrast asserted for every theme, previews in `data/ui-previews/`.

### Decisions
- A confirmed tool (open_file and friends with a position) is run by the router after the yes; its own result sentence is spoken, not rephrased by the model.
- The chat thread on disk is already redacted (memory/threads.py), so the reveal switch affects the activity and build logs, the briefing card and the status details, not saved chat text.
- `route_check` and `evalkit` now allow six offered tools and ~900 tokens, because the spec asks for the top six. They patch `brain._groq_tools` so nothing reaches the network.
- Proactive check-ins (off by default) now state facts about idle time; there are no jokes left.

### Needs your real screen, mic or phone
- Screen: the layout at your real resolution and scale, how the glow and orb look on your panel, Devanagari and Kannada glyphs (the font stack lists Noto fonts; Qt printed OpenType warnings for them here, which are silenced).
- Mic: that the tool chips and the "(offline)" prefix read well spoken, and that a failed tool being reported in one sentence sounds right.
- Providers: native function calling against your real Groq model (`GROQ_MODEL`; a model that rejects tools falls back to the JSON form), and the outage line with a real 429.
- Phone: the hand-off outbox actually syncing to the phone, and Telegram confirmations for the new file tools.

## Phases 32 to 35 (holo, 3D models)

### Phase 32: holo bridge client
- `jarvis/holo.py` runs `<HANDCTL_DIR>/.venv/bin/python bridge.py open|load NAME|reset|close` and checks the viewer's socket only by connecting to it (no token read, no port, nothing listened on).
  Tools in `actions/holo_tools.py`: open_holo, show_model, reset_holo, close_holo. Doctor line `holo: ready / not set up`.
- handctl's viewer only loads files from its own `models/` folder and reads that folder once at start. So `show` links `models/<name>/model.stl` into `<HANDCTL_DIR>/models/jarvis-<name>.stl`
  (a symlink, no copy, no handctl code touched) and restarts the viewer when the name is new to it. This writes symlinks into handctl's models folder; delete `jarvis-*.stl` there to undo.
- The bridge answers ok as soon as a load is queued, so an unknown name is only seen on the viewer's own screen. Jarvis therefore checks names itself first. `bridge.py open` returns before the camera is
  opened, so a busy camera shows up only as the socket never appearing; Jarvis waits 12 s and then says the viewer did not start. It cannot say the camera is the cause.
- A viewer Jarvis started is closed at exit (atexit) and by "close holo"; one that was already running is left alone at exit.
- After a good build, `modeler._show` shows the model only when `HOLO_AUTO=on` (default off; it starts the camera viewer); otherwise it says "Say show it to view it on the hologram."
- Checks use `scripts/fakes/fake_handctl.py` (a fake bridge.py whose viewer holds a real Unix socket) so nothing touches the real viewer or `handctl/models`.
- Not verified here: the real viewer with a real camera, that the viewer loads a symlinked STL (its `scan` uses `is_file()`, which follows links), and that a restart is quick enough.

### Phases 33 to 35: built
- `actions/modeler.py`, `scripts/model_check.py` (about 70 checks), 11 model and holo phrases in `core_check`, README section, `.env.example`, doctor line for openscad.
- Checked once with the real openscad 2021.01: a cube with a hole builds and reports correctly, a syntax error gives the one-line error.

### Needs the real thing
- openscad with real model code from your brain (quality of the .scad, how often the first compile fails), the slicer (`flatpak run com.prusa3d.PrusaSlicer` is the default and untested here),
  and the camera and holo viewer once the bridge exists.
- The wall thickness estimate samples 60 rays and skips meshes over 40000 faces; treat it as a hint.


## Phase 2: design system, globe screen, bubbles, command palette

### Built
- `jarvis/ui/design.py`, `status.py`, `globe.py`, `bubbles.py`, `stage.py`, `bottom.py`, `cmdk.py`, `shell.py` and `jarvis/features.py`; `scripts/shell_check.py` (about 170 checks, in `ci_checks.txt`).
- The new window is the default; `--classic` keeps the old dashboard. The ten existing pages (Chat, Activity, Media, Code, Notes, Study, Jobs, Web, Stats, Settings) open inside it unchanged.
- Small changes elsewhere: `events.hearing` and two lines in `ears.py`; `reduced_motion` in `themes.DEFAULT_UI`; a Reduced motion checkbox in Settings; `Dashboard` got `reduced`, `on_power`,
  `set_reduced_motion`, a `make` argument on `window.run`, and its tray "Show" now calls `self.bring_up()` at click time. `dashboard_check` now expects the new window by default and `--classic` for the old one.

### Decisions and limits
- The classic `Dashboard` is still built (hidden) because it owns events, tray, theme and quitting and the pages need its `Theme` and `Clock`. It goes away when the pages are rebuilt.
- "Listening" means the ears are recording after a wake word, push to talk or a follow-up; waiting for the wake word is "idle". "Offline" means offline mode or every provider's last call failed.
- Tools in the palette open Chat with a starter phrase and do not run; most need arguments and risky ones (shutdown, delete) must not fire from a keystroke.
- Unavailable entries: About JARVIS and Accent colour (planned), Study and Jobs while `STUDY` / `JOBS` are off. They are shown greyed, with the reason, and cannot be chosen.
- Reduced motion and low power both run the clock at 15 fps. Destination pages sit in a scroll area because some need more than 520 px of height.
- Frame time and memory are measured offscreen with software rendering; the numbers on a real GPU session will differ.

### Needs your real screen and mic
- Fullscreen on KDE Wayland (the app forces xcb as before), F11, and the look of the globe, stars and bubbles at your resolution and scale factor.
- Cursor parallax, particles moving away from the cursor and the globe tilt with a real mouse; smoothness of the scroll and the fade into a page.
- The globe actually following your voice: listening pulse with the real mic level, speaking rhythm from Piper, thinking while a real request runs, error and offline after a real failure.
- The bottom panel texts with a live Groq or Ollama, and the brain label switching to advanced on an advanced answer.
- Tab order and visible focus with a keyboard, Ctrl+K against the KDE shortcut set, and the UI process memory in a long session (the 250 MB check is a short offscreen run).
