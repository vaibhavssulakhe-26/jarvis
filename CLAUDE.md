# Jarvis

Personal voice assistant for Fedora KDE Wayland. PyQt6 window, openWakeWord, faster-whisper, Piper,
Groq as the brain, OpenRouter as the first fallback and Ollama as the offline fallback.

## Running
- `python -m jarvis.main` from the repo root, inside `.venv`. Never `python jarvis/main.py`: the package uses relative imports.
- `python -m jarvis.main --text` to type commands instead of speaking.
- `python -m jarvis.scheduling.reminders list` prints pending reminders.
- `python -m jarvis.doctor` prints diagnostics, `python -m jarvis.bench` times the eval phrases, `python -m jarvis.routines run|list|now <name>`.

## Dependencies
- `requirements.txt`, plus `openwakeword` installed with `--no-deps`.
- `psutil` for system status (memory, processor load, temperature).
- No APScheduler: reminders, including repeating ones, run on the one-second polling thread in `jarvis/scheduling/reminders.py`.
- `playwright` (browser control, uses Google Chrome). Optional system tools: `tesseract` (screen reading), `git`, `node`.
- System tools: `wpctl` (volume), `spectacle` (screenshots), `wl-paste` / `wl-copy` (clipboard), `kdotool` (active window).
  `scrot`, `gnome-screenshot`, `xclip` and `xsel` are used only as fallbacks.

## Configuration
All settings and keys come from `.env` (see `.env.example`), read in `jarvis/core/config.py`. Nothing is hardcoded.
- `GROQ_MODEL` text brain, `GROQ_VISION_MODEL` model used for reading the screen.

## How a command flows
`ears.py` hears it, `main.handle` tries `main.fast_path` (short unambiguous commands, no network), otherwise
`brain.think` picks an action from the registry in `tools.py`, and `main.execute` runs it. Tools register with
the `@tool` decorator; modules with their own tools are imported at the bottom of `tools.py`.

## Token budget
- `tools.pick_tools` returns at most 3 tools, or none for small talk and unmatched text. None means `brain.chat`: plain
  path, system prompt under 300 tokens, last 2 turns, each cut to 200 characters. Otherwise `brain.think` sends only those tools plus the rules
  that belong to them (`TOOL_RULES`).
- `brain._sent` prints `[provider ~N tokens]` for every request (counts only) and warns above 2000. `route` keeps a
  rolling 60 second total per provider (`GROQ_TPM`, default 8000; `OPENROUTER_TPM`, default unlimited) and skips a
  provider that has no room. A 400 in JSON mode is retried once, plain, with the same messages.
- Offline backup: `OLLAMA_MODEL` (default `llama3.2:1b`, falls back to the smallest installed model), skipped under 1.5 GB free.
- Time and date, simple reminders ("in ten minutes", "every 30 minutes", "at 7 pm") and the rest of the local
  commands never reach a model. `scripts/route_check.py` checks the routes with a mocked brain.
- `STT=groq` (or the older `JARVIS_STT`) switches speech recognition to Groq; `g` and `cloud` also count.

## Features and where they live
- Volume: `tools.py` (`set_volume`, `volume_up` / `volume_down` take an optional `by` percent).
  `fast_path` checks direction words before numbers, so "volume up by 10" raises by 10 instead of setting 10.
- Mute: `tools.mute` remembers the current level and sets volume to 0; `tools.unmute` ("unmute",
  "restore volume") brings back that level. Exact short phrases are handled in `fast_path` (`MUTE`, `UNMUTE`).
- Reminders: `reminders.py` stores them in `data/reminders.json` as `{"text", "due", "done", "every"}`;
  `every` is a repeat interval in seconds and is absent for one-shot reminders. Due reminders are spoken through
  `reminders.notify`. Missed repeats (laptop asleep) fire once and move to the next slot. Tools: `set_reminder`
  (`every_minutes` for repeats), `cancel_reminder`, `list_reminders`, `clear_reminders` in `tools.py`.
- Screen and clipboard: `screen.py`. `describe_screen` captures to the private runtime dir, downsizes to JPEG,
  sends it to the Groq vision model through `brain.look`, and deletes the capture. `read_clipboard` reads short
  clipboard text aloud and summarises long text with the brain. Both run only on an explicit request.
- System awareness: `tools.system_status` (battery, charging state, memory, processor load and temperature) and
  `tools.battery`. "how's my system" and "battery status" go through `fast_path`. The low-battery warning
  (20 percent, once until charged again) is in `companion.py`.
- Pending choices: a file question stays open for 60 seconds. `files.take_choice` resolves "second", "number two",
  "newest" and so on anywhere in the sentence; `files.hold_choice` repeats the options or re-asks on a garbled reply
  without searching again. `main.check_pending` handles yes / no, uses the question up once, and runs any extra words
  after the yes as a new command.
- Focus guard: `scheduling/guard.py` with `actions/windows.py` (kdotool) and `actions/guard_tools.py`. Off by default
  (`DISTRACTION_GUARD`, or "turn on focus guard"). Local rules first; unclear titles go to the brain in one batch.
  `scripts/guard_check.py` prints verdicts for sample titles.
- Translation: `actions/translate.py`. Result goes to the clipboard; only Latin-script text is spoken.
- Clipboard monitor: `actions/clipwatch.py`, off by default (`CLIPBOARD_MONITOR`). Offers one action for a link, error,
  code or long text; skips anything that looks like a key or password; keeps only a hash of the last clip.
- Palette: `ui/palette.py`. Sends the typed command through the `command` key in `core/state.py`; `main.command_loop`
  runs it. Bind `.venv/bin/python -m jarvis.ui.palette` to a KDE shortcut.
- Hand-off: `actions/handoff.py` appends to `<outbox>/phone.txt` or `laptop.txt` (`HANDOFF_DIR`, default `data/outbox`);
  files are copied to `<outbox>/files`.
- Code help: `actions/debug.py` (`debug_clipboard`) speaks a short answer and copies the full fix.
- Research: `research/topic.py` (`research_topic`, "research X") makes one plain brain call and writes a cited note to
  `data/notes/research-<topic>.md`. The older `research` tool still handles events and news.
- Brain fallbacks: `brain._try_groq` retries a 400 once on the plain path, a 429 moves to the next provider at once.
  `brain.code` is the plain-text call for code; it tries `CODE_MODEL` on `CODE_PROVIDER` (OpenRouter by default) first.
  Code is never requested through the JSON tool-calling path.
- Voice: `voice/voices.py` lists voices in `models/voices` and `~/piper-voices`. The choice is saved in
  `data/settings.json` and read before every spoken reply, so it changes at once. First-run default is `VOICE`
  (or the older `JARVIS_VOICE` / `ANA_VOICE`), else `en_US-ryan-medium`. `scripts/get_voices.py` downloads the extras.
- Coder: `actions/coder.py`. `build_project` plans the files, then one brain call per file into `CODE_WORKSPACE`
  (default `~/Projects/jarvis-builds`). `edit_file` and `find_bugs` describe the change and apply it only after a yes
  (`apply_edit` through the shared confirmation), keeping a `.bak`. `run_project` asks first, runs inside the
  workspace only, 20 second limit, refuses files that use sudo.
- Laptop control (`actions/apps.py`): app aliases (browser, terminal, VS Code), `close_app` (asks first),
  `switch_app`, `minimise_window`, `open_path`, `brightness` (needs brightnessctl), `open_site`. Windows are found
  by class with kdotool (`windows.py`). Only fixed commands run; nothing is passed to a shell.
- Research: `research_topic` searches, reads up to five pages (trafilatura, robots.txt respected), one small call per
  page and one final call, cached for an hour. "show me" opens the sources; `help_topic` ("I need help with X",
  "how do I X") decides between research, a docs page and a direct answer.
- Play: `actions/play.py`. `play_media` with a query hands the spoken words to `play.start`: it parses the kind (learning,
  music, video), searches yt-dlp metadata (`ytsearch8`, no download), ranks (10 to 90 minutes, teaching words, views and
  `STUDY_CHANNELS` for learning; official or top result for music), opens the best in `BROWSER` and keeps the rest for
  `play_next` ("next", "another one", "not this one"). It only asks when the topic is missing; the answer is taken by
  `play.answer`. `scripts/play_check.py` uses saved results.
- Languages: `core/lang.py` holds the listen language (`STT_LANGUAGE`, or "listen in Hindi / Kannada / English / auto" for the
  session, tool `set_language`), the reply language ("reply in X", or Devanagari / Kannada script in the utterance) and
  `reply_hint`, one line added to the brain prompt. `stt.py` sends `STT_MODEL` to Groq with no language unless one is set, and
  a short prompt in that language; the local fallback is `STT_LOCAL_MODEL` (default `small`, multilingual). `voices.path_for`
  picks the Hindi voice (`hi_IN-pratham-medium`) for Devanagari text. With no Kannada voice, `voice.say` copies the text to the
  clipboard and says so in English. No online TTS. `scripts/language_check.py`.
- Persona: `brain.PERSONA` stays under 250 tokens; `chat_system` adds the pet name. `route_check.py` keeps a plain chat
  request under 400 tokens.
- Proactive chat: `scheduling/proactive.py`, off unless `PROACTIVE` is low or normal ("be chattier", "be quieter", "stop talking
  for two hours" via `actions/proactive_tools.py`). Idle means no interaction (`touched_at` in the state file), 40 minutes at low,
  20 at normal; at most 1 or 3 lines an hour, 15 minutes apart; silent in quiet hours, with the focus guard on, during the digest,
  or while speaking; two ignored lines in a row mean four hours of silence. Lines are local, with one small model call every
  four hours at most. The battery and late-night warnings remain in `companion.py` (`JARVIS_PROACTIVE`).
  `scripts/proactive_check.py` runs on a fake clock.
- Film voice: if `models/voices/jarvis.onnx` and `.onnx.json` exist it is listed as "jarvis". The json `dataset` field must match
  the file name. `models/voices/` and `*.onnx` are git-ignored.
- Speech output: every spoken line goes through `voice/speech.py` (`clean`): no markdown, symbols, links (one "link on screen"),
  addresses or emoji; `&` and `%` are spoken as words. Code, lists, tables, drafts and anything over five sentences or 450
  characters stay on screen, are copied, and Jarvis says "Done, it's on your screen and copied." Three or more sentences are cut
  to two (`speech.SHORT_SENTENCES`). A tool that must be read in full returns `speech.Full(text)` (file read aloud, short clipboard, the digest).
- Interrupting: `voice.stop()` kills the player process and drops the queue (a generation counter), and is harmless when
  nothing is playing. Mechanisms: the spoken words stop / stop talking / quiet / enough / shut up / ruko / चुप (`main.STOP`);
  the wake word at threshold + 0.3 while Jarvis talks (`Ears._interrupt`, logged as "speech cut off by the wake word"); the STOP
  button or Ctrl+. in the window and `python -m jarvis.voice.voice --stop` (both set `stop_at` in the state file).
  `scripts/stop_check.py` uses a fake process and a fake audio stream.
- Player: `actions/mpvctl.py` runs ONE mpv (`PLAYER=mpv`, the default, when mpv is installed; `PLAYER=browser` or no mpv keeps the
  browser) over an IPC socket in the runtime dir. Music is audio only, videos get a window. `next`, `play next`, `another one`
  load the next saved result into the same mpv (`play.NEXT`, never a search). While mpv runs: pause, resume, stop playing,
  louder, quieter, skip forward, go back (`player_control`). A search is retried once; two failures give one friendly line.
  `scripts/player_check.py` uses a fake socket.
- Languages: STT defaults to English (`STT_LANGUAGE=en`). In auto, only en, hi and kn are accepted; anything else is
  re-transcribed once as English (`lang.allowed`). `reply_hint` always limits replies to English, Hindi or Kannada.
- Local phrases: `main.fuzzy` matches control phrases (chattier, quieter, stop talking for X, listen in X, use the X voice, what
  voices do you have) with difflib, no model call. A missing jarvis voice says where the files go.
- Tokens: the tool path uses `PERSONA_SHORT`; history is the last 2 turns at 200 characters and holds the action plus a short
  line, never arguments or drafts. Old tools are offered again only when Jarvis's last line was a question
  (`pick_tools`). A tool's own line is spoken as it is; there is no second model call to phrase it. Draft and write requests
  get `DRAFT_TOKENS`. After an `ask`, the prompt tells the brain not to ask again; build requests choose defaults.
- Player crash: on this laptop mpv's default Vulkan renderer crashes (SIGTRAP inside libvulkan_radeon) on real video frames, so `mpvctl`
  adds `MPV_ARGS` (default `--gpu-api=opengl --hwdec=no`; set it empty to pass nothing). mpv's stderr goes to `<runtime dir>/mpv.log`, and a failed
  start (up to three candidates) names that path in the one spoken line.
- Listening gate: `voice/gate.py` (`judge`) decides for every transcript, before any brain call. An utterance is taken only when the wake word started it or is in
  it, push-to-talk / the Talk button started it, or it is the one reply inside a follow-up window. The window (`FOLLOWUP_SECONDS`, default 6) opens only when Jarvis
  just asked a question (a pending question, or a reply ending in "?") and the request did not fail (`traces.last_failed`); the first sound uses it up, so it is one turn,
  and "Yes?" / errors / status lines never re-arm it. Dropped: under 3 words with no wake word (yes, no, numbers and ordinals still count as answers in the window),
  known Whisper hallucinations (`stt.is_hallucination`), repeated syllables and filler ("da da da", "hmm", "I suppose"), anything captured while music or Jarvis's voice
  played unless the wake word was said. Every verdict is logged as a `hear` event ("accepted (wake word): ...", "dropped (no wake word): ...") for the Activity page;
  `hear` is never a chat message. `scripts/ambient_check.py` feeds 15 fragments and expects 0 brain calls and 0 chat messages.
  The old rule "thanks / that's all / bye / stop listening close it" still applies (`END`). While media plays a command needs the wake word.
- Speech recognition: `stt.transcribe` returns "" for clips under 0.4 s or too quiet and for known made-up transcripts (`is_hallucination`).
  `STT_HINTS` words go into the prompt.
- Capabilities: `actions/capabilities.py` answers "what can you do" / "help" from `TOOLS`; spoken summary, full list on screen.
- Stop control: `main._handle` first checks `procs.alive()` ("stop the app", "stop it" when nothing is speaking), then `stop_media` ("stop",
  "stop music", "quiet", "enough" quit mpv, "pause" pauses it, only if `mpvctl.running()`), then the speech stop words. `mpvctl.stop` also kills a stuck
  mpv and removes the socket; it runs from atexit, SIGTERM, the window's quit and the STOP key (`main.check_stop_key` polls `stop_at`). While media
  plays `Ears._idle` never records without the wake word.
- Nickname: `USER_NICKNAME` (default `USER_NAME`) becomes `config.PET_NAME`, which every greeting already uses.
- Provider truth: `brain.HEALTH[provider]` holds the result of the last real call (set by `_record` in every Groq, OpenRouter and Ollama call; `groq-strong` and
  `groq-vision` are tracked apart so they never mark the fast model down). `provider_state` / `provider_status` (dashboard pill, Brains cards, self block) read only
  that: "last call worked 2 minutes ago", "last call failed, it returned HTTP 500", or "not called yet this session". Never a ping. A provider that fails is skipped
  for the rest of the turn (`route(skip=)`), the working one answers and Activity says who failed. One failure message per turn: `brain.begin_turn()` (from
  `main.handle`), `say_failure`, and `outage_line()` returns "" when something was already said. Stats shows today's tokens per provider (`stats.usage` returns today's
  row only for today).
- Rate limits: when Groq and OpenRouter both answer 429 in one `brain.route`, it skips the cloud for `OFFLINE_SECONDS` (60) and the cause is said once (with the offline answer, or by `outage_line`).
  `brain.log_usage` counts answered requests per provider and day in `data/usage.json` (counts only).
- Notes search: `memory/rag.py` indexes `.md`, `.txt` and `.pdf` from `NOTES_DIR` (default `data/notes`) plus `RAG_FOLDERS` into `data/rag.db`
  (FTS5, BM25). `actions/rag_tools.py`: `search_docs` sends the top 3 chunks (700 characters each) and appends the file names itself;
  `reindex_notes`. `summarise_file` tries `rag.find` first. Startup reindexes in the background only when files changed.
- Study: `actions/study.py`, data in `data/study.json` and `data/roadmap.md`. An open quiz or check-in question lives in `study._session`;
  `main._handle` calls `study.take` right after `check_pending`, so the next sentence is the answer. Grading asks the model, with keyword
  overlap and a built-in question bank as the offline fallback. `week_summary`, `streak` and `good_morning` use no model.
- Focus: `scheduling/pomodoro.py` (state key `pomodoro`, a one-second thread only while a timer runs), tools in `actions/focus_tools.py`
  (`start_focus`, `start_break`, `stop_focus`, `good_morning`, `quick_note` to `<NOTES_DIR>/inbox.md`). A finished session credits `study.add_minutes`.
  `FOCUS_MUTE_NOTIFICATIONS=true` uses Plasma's notification Inhibit over QtDBus, which ends by itself if Jarvis exits.
- Screen text: `screen.read_screen` captures (spectacle, grim fallback), runs tesseract, drops lines that look like secrets, and sends at most
  3000 characters. Missing tesseract raises a ToolError that names `sudo dnf install tesseract`.
- Dictation: `voice/dictate.py`, off unless `DICTATE_KEY` is set. It needs the input group; `python -m jarvis.voice.dictate --once` is the shortcut mode.
  The state key `dictating` makes `Ears` ignore the mic meanwhile.
- Stats and eval: `scripts/eval_phrases.py` writes `data/eval/<date>.json`; `actions/stats.py` (`jarvis_stats`) reads it and `data/usage.json`.
- Coder loop: `build_project` detects the kind (`coder.detect_kind`: script, flask, fastapi, static, pyqt), writes `.jarvis.json` into the project,
  then `check_and_fix` runs `verify` and `fix_once` up to `MAX_FIXES` (4). Flask and FastAPI get `<project>/.venv`; `install_deps` runs only after a
  yes and only for plain names from `requirements.txt`. Generated code runs with `procs.clean_env()` (no API keys), never with sudo or rm -rf
  (`UNSAFE`), and files are written through `write_project_file` (workspace only, one `.bak`). Child processes live in `actions/procs.py`
  and die on exit. `run_project` starts servers and Qt apps in the background; `stop_project`, `fix_last_error`, `add_feature`, `explain_file`,
  `git_init_project` are the other tools.
- Browser: `actions/browser.py` (Playwright, profile `data/browser-profile`, one worker thread owns the browser, closed on exit and after
  `BROWSER_IDLE_MINUTES`). The safety rules are in code: `refuse_typing`, `risky_click` with `_asked` (a risky click only runs after
  `_describe_click` asked and a yes arrived), downloads cancelled until `confirm_download`, `safe_url` allows http and https only, and
  `page_prompt` marks page text as data. "open <domain>" and "search X on Google" use it only when `browser.ready()`; otherwise the old
  `open_site` / `web_search` run. `coder.open_web` uses it for "run it" on web apps.
- Dashboard: `ui/dashboard/` (`python -m jarvis.main` opens it; `--no-ui` is headless, `--text` is typed). `themes.py` (no Qt: presets, hue, saving into
  `data/settings.json` next to the voice choice) and `theme.py` (the live `Theme`: every colour and the whole stylesheet come from it, a change
  fades 400 ms, glow sprites are cached per theme) are the only places with colour values. `widgets.py` holds the `Clock` (one timer, 30 fps, 15 in
  low power, stopped while hidden), `Orb`, `RingGauge`, `Panel` and `MemoryGraph`, all QPainter, no graphics effects. `pages.py` has the eight pages
  and the confirm bar; `window.py` the window, tray and `quit_all`. The voice loop is `ui.start_core`; the window gets lines through `events`
  (`you`, `jarvis`, `sys`, plus `route` and `provider` from `main` and `brain.route`) and a Qt signal. `events.out_level` is the loudness of the
  line being spoken (`voice.envelope`). Voice theme changes go through `theme_tools.change_theme`, which saves and sets the `theme_at` state key.
- Confirmations: `check_pending` accepts a loose yes (the pending tool's own verb with filler, such as "close it") and never routes the rest of the sentence
  again. `apps.THIS_WINDOW` words name the focused window in the question. `capabilities.ASK` / `CAN` answer from `TOOLS` (`answer_can`). `tools.ALWAYS` is
  empty: `remember` is offered only for remember, note or save. `coder.is_vague` makes `build_project` ask one question (`take_spec` takes the answer).
  Browser: `BROWSER_SEARCH` (default duckduckgo), `is_blocked` stops at captcha pages (`browse_external` hands the URL to xdg-open), `_Worker.run` relaunches
  once on `TargetClosedError`.
- Home page extras: `events.busy` (set in `main.do_tool` through `agent_of`) drives the Active agents panel, `brain.LATENCY` the provider cards,
  `rag.last_indexed` the memory panel; the window size is saved by `themes.save_window`. `scripts/dashboard_check.py` saves previews to `data/ui-previews/`.
- Check scripts in `scripts/` run without a mic or accounts; each feature has its own `*_check.py`. `scripts/all_checks.sh` runs them all.

## Conventions
- No docstrings that restate the function name, no banner comments, no emoji.
- Tools return one short sentence to speak, and raise `ToolError` with a speakable message on failure.
- Do not edit `.env` or anything under `data/` by hand; test against a scratch copy of `reminders.FILE`.

- Playback and wake (late additions): mpv runs at `MPV_VOLUME` (50); `Ears._begin` ducks it to 15 over IPC (`mpvctl.duck`) and `_idle` restores it
  when the follow-up window ends. While media plays the window no longer records without the wake word (music must not produce transcripts), so
  each command during playback starts with the wake word, for example "Alexa, stop". `MUSIC_VIDEO=true` makes songs open a video
  window; "watch X", "show me X" and "play a video of X" always do. `main.collapse_repeats` turns "stop playing. stop playing" / "next next" into
  one phrase before routing. `WAKE_DEBUG=1` prints wake scores above 0.15; `BARGE_THRESHOLD` is separate from `WAKE_THRESHOLD`; extra custom
  `.onnx` wake models in `models/` load next to hey_jarvis. `python -m jarvis.actions.mpvctl --pause|--stop|--next` for keyboard shortcuts.

- Browser launch: `chromium_sandbox=not _is_root()`, so Chromium keeps its sandbox (Playwright adds `--no-sandbox` otherwise). `browser.goto` loads the
  page, waits for `load` and closes a leftover about:blank tab. Real-time questions (weather, news, scores, prices) never open a browser:
  `research/live.py` (`live_answer`, matched in `main.DIRECT` by `live.is_live`) searches DuckDuckGo's HTML endpoint with requests, reads the top three pages
  with trafilatura, makes one small brain call (or uses the snippets) and names the sources. A sentence with "open" does not match.
- `BRAIN=hybrid|offline` (`config.brain_mode()`, `config.offline()`): offline makes `brain.route` local only and turns off Groq, OpenRouter, the vision
  call, the warm-up and cloud STT. The dashboard top bar shows it.
- Themes: each preset keeps its panel and background at the accent's hue; `dashboard_check` prints every accent and asserts purple (hue 275 to 295 and red at least 70 percent of blue), plus the pink and red hue ranges and that each panel tint follows its accent.
- Media: `play.rank` drops candidates that fail the ranking (live streams stay last as a fallback). `play._state["now"]` is the item that actually started;
  `play.now()` gives (item, queue index) for the Media page and returns None only when `mpvctl.active()` is false.
- Notes page: reads `rag.scan()` (NOTES_DIR plus RAG_FOLDERS, .md .txt .pdf), links notes that share keywords, and shows indexed and on-disk counts.
- Study: the rail entry is hidden unless `STUDY=on` (`window.show_study`); the page shows the next roadmap item as a 20 minute block with a Start button
  (`start focus 20`).
- Voice: `voices.best()` picks the highest quality installed English voice when nothing is saved or set in `VOICE`; `voices.length_scale()` is 0.92 divided by
  `VOICE_SPEED`; `voice._speak` synthesises the next sentence while the current one plays; at most two sentences are spoken.
- Routines: `routines/__init__.py` (parser for `data/routines.md`, state in `data/routines-state.json`, `due`, `run_due`, file lock), `routines/morning.py`
  (gather, one brain call under 750 estimated tokens, template fallback, saves `data/briefings/<date>.md`), `routines/ical.py` (read-only iCal from
  `CALENDAR_ICS_URL`, simple RRULE), `routines/triage.py`, `routines/runner.py` (startup catch-up, five minute loop, once-a-day spoken briefing that claims
  `digest_last` so the old digest does not repeat it). Tools in `actions/routine_tools.py` and `mail.draft_reply`. Email text that matches
  `morning.SUSPECT` is withheld from the model. `mail.save_draft` is the only write to the mailbox (APPEND to Drafts); nothing in the code imports smtplib.
- Doctor and traces: `jarvis/doctor.py` (items with pass, warn, fail and a fix hint; keys only as set or not set), `actions/diag_tools.py`
  (`run_diagnostics`, `show_failures`, `which_model`, `run_benchmark`), `jarvis/traces.py` (data/traces.jsonl, `main.handle` begins and ends each trace,
  `events.emit` supplies route and provider, `do_tool` supplies tool and failures; a repeat of three or more words with the same numbers, or a sentence
  starting "no", "I said", "I meant" and so on within 90 seconds marks the earlier line corrected). `jarvis/evalkit.py` holds the 30 phrases and the
  router probe used by `scripts/eval_phrases.py`, `jarvis/bench.py` and `scripts/replay_failures.py`.
- Offline model: `brain.pick_ollama_model(names, free)` takes `OLLAMA_MODEL` when installed, else the largest installed chat model that fits (under 2 GB free
  1B, 2 to 4 GB up to 4B, above 4 GB up to 9B). It is chosen at startup, printed, and shown in the dashboard Core panel.
- New checks: `live_check`, `routines_check`, `doctor_check`, `traces_check`.
- Wake word anywhere and echo: `Ears.roll` keeps 4 seconds of idle audio; on a wake hit `ears.take_preroll` keeps speech spoken before the wake word
  ("play something Jarvis") and `drop_name` removes the name from anywhere in the transcript. `voice/echo.py` (`EchoGate`) learns the microphone level
  during Jarvis's own speech or media playback and only a clearly louder voice (3 blocks, 1.8 times the echo, 0.4 s cooldown after output stops) starts a
  "barge" recording, in which only stop words (`echo.is_stop_phrase`) are acted on. `jarvis/redact.py` (`mask`) is applied to traces, notes, the quick note
  inbox, archived conversation turns and the `heard:` log line.
- Platform layer: everything OS-specific lives in `jarvis/platform/` (`__init__` has the interface, `API` lists the calls; `linux.py`, `mac.py`). Other code
  calls `platform.clipboard_write`, `open_target`, `capture_screen`, `active_window`, `notify`, `power`, `volume_*`, `media_control`, `listen_key`,
  `send_paste`, `install_schedule` and so on, never a command. A call a backend lacks raises `platform.Unsupported` (a `ToolError`: "... is not supported
  on this system."). `scripts/platform_check.py` scans `jarvis/` for Linux or Mac commands outside the backends. `ToolError` now lives in `core/errors.py`
  (still importable from `actions.tools`).
- Profiles and setup: `JARVIS_PROFILE=name` (`config.PROFILE`) reads `.env.<name>` before `.env` and moves `config.DATA` to `data/profiles/<name>`, the
  runtime folder and the state file to per-profile paths. `python -m jarvis.setup` (and `scripts/install.sh`) is the first-run wizard (standard library only).
- CI: `.github/workflows/checks.yml` runs `scripts/ci_run.sh`, which reads `scripts/ci_checks.txt` (a name, optionally followed by `linux`), on Ubuntu and
  macOS with Python 3.11 and `QT_QPA_PLATFORM=offscreen`.
- Jobs (`JOBS=on`): `jobs/tracker.py` (data/jobs.json), `jobs/analyse.py` (extract, compare with data/profile.md, one brain call, `LAST`), `jobs/drafts.py`
  (clipboard plus `mail.save_draft(..., reply=False)`), `jobs/mailflag.py` (recruiter mail words, suggestions in data/job-suggestions.json, applied only through
  the confirm tool `job_mail_updates`), `jobs/interview.py` (spoken mock interview; `main._handle` calls `interview.take` after `study.take`),
  `actions/job_tools.py` (tools are registered only when JOBS=on) and the Jobs dashboard page.
- Small JSON files under data/ are read and written through `core/jsonfile.py` (`read(path, default, kind)`, atomic `write`); settings.json goes through `voices.read_settings` / `write_settings`.

- Listening in noise: `voice/vad.py` (Silero via onnxruntime, then webrtcvad, then loudness; `Endpointer` ends at 0.8 s of silence or `MAX_RECORD_SECONDS`, 12),
  `voice/ptt.py` (`PTT_KEY` or the Talk button, hold to record, no wake word), `voice/listen.py` (crowd mode: `CROWD_MODE`, Settings, "crowd mode on/off"; wake word for
  every command, no follow-up window, threshold from the noise floor). `Ears._finish` always returns to idle. `NOISE_SUPPRESS=on` runs `vad.denoise` on a recording.
  `events.mic` holds floor, threshold, mode and detector for the meter and `doctor.check_listening`. `scripts/listen_check.py`.
- Chat: `memory/threads.py` keeps one shared thread (typed and spoken, redacted) in `data/chats/`; `main.start` attaches it to the event bus. `ui/dashboard/chat.py` is
  `ChatView` (the Chat page, and the compact dock on the other pages). `actions/attach.py` answers questions about a dropped PDF, text or image. `scripts/chat_check.py`.
- Quality and tiers: `brain.chat` uses `quality_system`, 12 turns from the thread and `QUALITY_TOKENS` when `QUALITY_MODE` is on (default); tool routing is unchanged.
  `brain.generate(messages, max_tokens, hard, on_delta, want_json)` returns `(text, tier)`: `strong` (`GROQ_STRONG_MODEL`, daily cap, rests a minute after 429), `fast`,
  `offline`; local commands emit tier `local`. `brain.is_hard` and `brain.clarify_hint` decide. `route_check` measures the chat budget with quality off.
- Streaming: `brain.chat(text, on_delta)`, `voice/stream.py` (`Streamer` speaks the first sentence early), `voice.say(text, skip, limit)`, `speech.shorten(text, limit)`; events
  `stream` and `stream_end` feed the chat bubble.
- Long-term memory: `memory/facts.py` writes `data/memory.jsonl` (redacted, one fact per line) and searches it with an in-memory FTS table; `allowed()` refuses secrets,
  health words and other people; extraction runs after five quiet minutes, on new chat and at exit. Tools in `actions/recall.py` (`recall_memory`, `show_memory`, `forget`).
- Browser agent: `actions/web_agent.py` (`browse_agent`): `make_plan` on the strong tier, `decide` on the fast tier, `observe` reads `aria_snapshot` plus text, `act` reuses
  `browser._inspect`, `risky_click`, `browse_type` and `_guard`. `confirm` uses `main.PENDING` with the `agent_confirm` tool. `abort()` is called by the Stop button,
  `check_stop_key`, the stop words and `AGENT_ABORT_KEY`. `RUN` feeds the Web page. `scripts/agent_check.py` needs Playwright and a browser.

- Telegram: `telegram.py` (TELEGRAM=on, `TELEGRAM_BOT_TOKEN`, requests long polling against `TELEGRAM_API`, which only the check changes). The first private chat that sends the six
  digit code printed at start becomes the owner (`data/telegram.json`); strangers get no reply and five wrong guesses change the code. Owner text runs through `main.handle` with
  `main.REMOTE.gate` set and `voice.capture()` collecting what would be spoken. `Gate.blocked` refuses send/delete/power tools (`NEVER`) and coder/browser agent tools unless
  `TELEGRAM_ALLOW_AGENT`; confirm-risk tools are held in `telegram._s["pending"]` for a yes/no from that chat (`check_pending` is off for remote commands). Forwarded
  messages are never commands; text is capped, masked in logs, rate limited (`TELEGRAM_RATE`). `notify` / `notify_once` send reminders, briefs, digests and alerts.
  Slash commands: /brief /email /tasks /status /stop. `python -m jarvis.telegram --unpair`. Doctor line `telegram`.
- Planner: `timetable.py` (data/timetable.md, data/deadlines.md, `parse_date`, `parse_class`, `brief_lines`, `focus_hint`), `tasks.py` (data/tasks.md), `alerts.py`
  (data/alerts.jsonl, `add(source, message, quiet_for=)`, `describe(exc)`), tools in `actions/planner_tools.py`, direct phrases in `main.DIRECT`. `routines.run_one`, the runner loop and the
  reminder, page watch and old digest loops write alerts; the dashboard top bar shows an ALERTS chip.
- Brief: `morning.gather` adds classes, deadlines, tasks, the study set and the alert count; one brain call (`MAX_PROMPT_TOKENS` 640 plus `OUT_TOKENS` 150), template fallback with
  `timetable.focus_hint`. `routines.runner.push` shows it on the dashboard, `telegram.notify_once("briefing_pushed")` sends it once a day, `announce` speaks it.
- Email digest: `routines/maildigest.py` (`digest`, `rule_category`, `sort`; unclear ones go to one brain call with sender and subject only; instruction-like mail is withheld).
  `mail.fetch_recent` reads `SINCE` the day, read only, PEEK. The routine line `digest-time` uses `EMAIL_DIGEST_TIME` (18:00); `routines.seed_digest` adds it once to an older routines file.
- Notes quiz: `actions/notes_quiz.py` (`quiz_from_notes`, `review_due`, `weak_note_topics`, Leitner `grade_card`, `daily_set`). The round lives in `study._session` with kind "notes"
  (`study.take` hands over to `notes_quiz.take`); cards are `data["cards"]` in data/study.json.
- Offline wiki: `research/wiki.py` (`OFFLINE_WIKI`, optional libzim, `set_pack` for tests, `wiki_answer`), doctor line `offline wiki`. "what is X" uses it only while `config.offline()`.
- Web helper: `actions/webproject.py` (`make_website` via `coder.build_project`, `a11y_pass`, `preview_site` on 127.0.0.1 with a free port, `stop_preview`, `export_site`).
  Its tools belong to the "coder" agent group, so the phone gate treats them as agent tasks. Nothing deploys or pushes.
- New checks: `telegram_check`, `timetable_check`, `alerts_check`, `digest_check`, `study_notes_check`, `wiki_check`, `webproject_check`.

- Agent: `brain/agent.py` (`pick` = `tools.rank_tools(text, 6)`, `turn`, `execute`, `reply_from`). The local router in `main` (direct, fast_path, pending, study, files) runs first; otherwise `agent.turn` when tools matched,
  else the streaming `brain.chat` (whose system prompt now holds `brain.self_block()`). `brain.tool_turn` is native function calling on Groq (`_groq_tools`) and strict JSON through `route` elsewhere
  (`_flatten`). At most 3 tool rounds, 3 calls a round; all-ok runs of one or two tools skip the second model call unless the tool is in `DATA_TOOLS`. A `failed` tool still failed at the end becomes
  `failure_sentence` and replaces the model's text; `Ask` (core/errors) is a question, never a failure; confirm tools go through `main.run_tool` (and the Telegram gate). Offline replies start with "(offline)".
  Tests must patch `brain._groq_tools` (route_check and evalkit do) or they reach the network when a key is set.
- Brain state: `brain.FAILED`, `RETRY` (Retry-After or "try again in 5m"), `why_down`, `provider_status`, `_go_offline` (one line per outage), `outage_line`, `LAST_PROVIDER`.
- Files: `core/access.py` (`readable`, `denied`, `FILE_DENY`) is applied in `actions/files.py`, `memory/rag.py`, `actions/documents.py` and `actions/file_tools.py` (`list_folder`, `open_file`, `read_text_file`, `describe_image`;
  a position such as "4th" is resolved against the sorted list and confirmed). `handoff.send` reads its line back.
- UTF-8: every text file, `read_text`/`write_text`, `open` and text-mode subprocess call names `encoding="utf-8"`; streamed API replies set `r.encoding`; `main.utf8_streams()` runs at start.
- Traces keep `route`, `tool` and `error` for a failure (`traces.fail(reason, tool=)`). `scripts/core_check.py` writes `data/core-check.json` (`stats.core_rate`).
- Dashboard v3: `ui/dashboard/window.py` (icon rail, slim top bar with `pill`, QSplitter drawer, `backdrop` painted by the window), `theme.py` (`readable`, `contrast_pairs`, `backdrop`, `accent_text`, `surface`),
  `themes.py` (Ice default, charcoal), `privacy.py` (`show`, reveal), `pages.py` (`Home` with the orb as a background layer and `chat`, `Activity`, `Code`), `chat.py` (cards, chips from the `tool` event, cursor).
  Events: `sys`, `route`, `tool`, `alert`, `provider` go to Activity; `build` to the Code page; the chat thread only holds the conversation. Colour values live only in `themes.py`.
- 3D models: `actions/modeler.py` (`make_model`, `revise_model`, `prepare_print`). The brain writes OpenSCAD through `brain.code`; `unsafe` refuses reads outside `models/`, shell calls and
  empty drawings; `compile_scad` runs the openscad CLI (60 s, 3 GB limit, `_run` is what the checks replace); `inspect` uses trimesh and numpy for size, `BED_SIZE`, watertight, wall estimate,
  loose pieces and overhangs. Files live in `models/<slug>/v<N>/` plus latest copies; a compile error is retried once with the first error line. A real-world fit word with no number
  makes `make_model` ask once (`take_answer`). `prepare_print` copies to `models/ready/` and starts `SLICER_CMD`; nothing in `jarvis/` may talk to a printer (`model_check` greps for it).
  Telegram: `prepare_` is in `NEVER`. After a good build the model is shown on the hologram only when `HOLO_AUTO` is on; otherwise the line ends with "Say show it to view it on the hologram."
- Holo: `holo.py` (HANDCTL_DIR, bridge.py through handctl's venv python, `show` links the model into `<handctl>/models/jarvis-<name>.stl` and restarts the viewer for a new name, `stop` at exit only
  closes a viewer Jarvis started) and `actions/holo_tools.py` (`open_holo`, `show_model`, `reset_holo`, `close_holo`). The `show ...` DIRECT entry sits first so "show the bracket" is not a video search.
  Checks must use `scripts/fakes/fake_handctl.py` and set `HANDCTL_DIR`, or a build would start the real viewer.


- References: `core/refs.py` remembers the last model, file and project (`remember`, `latest`, one hour). "open that", "show it", "view it in hologram", "open it" go to
  `ref_tools.open_last` (guarded by `refs.latest()`; the hologram words mean the newest model). Model names match loosely (`modeler.match`: spaces, dashes and underscores
  ignored, then a close-spelling fallback), also in `holo.resolve`. `capabilities.is_generic_can` keeps "can you build apps?" local; a question about a concrete thing
  ("can you build a 40 centimeter cube?") goes to the agent, which has the self block and is told to answer, not run the tool. `scripts/context_check.py`.
- Overhangs: `modeler.overhang` ignores faces on the plate (all corners at the lowest z), counts only faces steeper than 45 degrees above it, and turns inside-out meshes
  the right way first. A cube and a 45 degree chamfered box report none (`model_check`).
- Holo start: `holo.start` runs handctl's `hand_mouse.py --holo` itself with stderr in `<runtime dir>/holo-viewer.log` and waits up to 20 s; a failure says the first useful
  line ("ModuleNotFoundError: No module named 'evdev'"). `scripts/fakes/fake_handctl.py make(folder, viewer=crash|silent|slow)` fakes those cases.
- WhatsApp: `messaging._prepare_message` refuses text with no letters or digits (empty, "?"); the confirmation quotes the exact text; text with non-ASCII characters is put
  on the clipboard and pasted (`platform.clipboard_write`, `send_paste`), never typed key by key, and refused when there is no clipboard tool. The spoken results say what was
  pressed and that delivery cannot be verified. `scripts/messaging_check.py` uses Hindi and Kannada.
- Dashboard (daily chat, status): `threads.rollover()` starts a new chat when the current one has messages from an earlier day (called on the first message, at start and from
  the window's slow tick). The System, Brains and Agents panels on Home are folded into the top pill (`Home.status_block`, hidden until the pill is clicked); status rows
  pad labels so a value never touches its label (`pages.pad` in rich text).

- Local-first brain (`BRAIN_MODE=local_first`, the default; `hybrid` keeps the old cloud-first order, `offline` or the older `BRAIN=offline` never calls the cloud): chat, simple questions and tool plans
  go to Ollama. The cloud, called "advanced", runs only when the sentence says "use advanced", "think hard" or "go deep" (`advanced.USER_WORDS`) or the work is heavy: `brain.code`
  (code and OpenSCAD), `ask(..., advanced=True)` (long document summaries, the research brief), the web agent plan, chat with debug or code-writing words, tool plans with several steps and
  screen vision. `brain/advanced.py` holds the rules: `budget()` (daily cap `ADVANCED_DAILY`, 40; under 10 left it raises `Ask` and parks the request as the `advanced_confirm` pending
  question, a yes replays it through `main.check_pending`; background threads and phone commands are never asked), `ambient` (noise, failure lines and Whisper phantoms never go out) and
  `cloud_view` (the system text, two earlier turns without failure lines, 400 characters each). Chat sends the cloud `brain.cloud_system` (no memory, facts or self block). The turn state is
  per thread and ends with `brain.end_turn()`. Calls are counted as `advanced` in `data/usage.json` (not added into the provider totals); replies carry the tier `advanced` (ADVANCED badge),
  `local model` or `offline`. A cloud failure or a used-up day gives one spoken sentence and the local answer. Local model: `pick_ollama_model` takes 1B under 2.5 GB free and up to 3B above
  (sizes come from `note_models`, which reads Ollama's own parameter counts), `num_ctx` 2048 (4096 for a 3B model with room), `keep_alive` 5m, one request at a time (`_ollama_lock`), other
  loaded models are unloaded first. `brain.local_status()` and doctor show model, free memory and whether it fits. `scripts/local_first_check.py` covers every path with fake providers.

- New window (phase 2): `jarvis/ui/shell.py` is the default window; `--classic` opens `ui/dashboard/window.py` as before. The shell builds a hidden classic `Dashboard` as its engine (events, tray,
  quit, theme, the `Clock`) and re-parents its ten pages (all but Home) into `Destination`, which adds a Back and Home bar inside a scroll area. `shell.run` is `window.run(make=Shell)`.
  `ui/design.py` has the tokens (colour, `SPACE`, `RADIUS`, `MOTION`), `contrast_pairs` (all at least 4.5, asserted), `readable` (lifts any user accent), the cached `backdrop` and `glass`,
  and `budget(low, reduced)`: normal 30 fps, 300 particles, 1100 globe points; low power 15 fps, 80 particles, 420 points; reduced motion also stops drift, parallax and transitions.
  Both flags live in `themes.DEFAULT_UI` (`low_power`, `reduced_motion`), set by `Dashboard.set_low_power` / `set_reduced_motion` (Settings page, palette) which call `on_power`.
  `ui/status.py` (no Qt) turns real state into one of six states (`resolve_state`: error, offline, speaking, thinking, listening, idle) from `Snapshot`: the state file, `voice.SPEAKING`,
  `events.hearing` (set by `Ears._begin`, cleared by `_reset`), a `Tracker` on the event bus (recent failure, last tier, activity) and `brain.provider_state` (read twice a second, never a ping).
  `ui/globe.py` (`LOOKS` table, `Globe`, `StarField`), `ui/bubbles.py` (`World` spring physics with a projection pass that keeps pairs at `2 * rc` apart, `Bubble` widgets with the label inside the circle),
  `ui/stage.py` (one widget, one paint per frame; scroll between globe and bubbles with `scroll_to`), `ui/bottom.py`, `ui/cmdk.py` (palette), `jarvis/features.py` (registry: sections, settings, every tool;
  `search` is fuzzy; `available=False` with a `why` for what is not built or switched off). Actions: `globe`, `page`, `toggle`, `window`, `tool` (opens Chat with a starter phrase, never runs it), `unavailable`.
  `scripts/shell_check.py` (offscreen) also saves `data/ui-previews/globe-<state>.png`, `globe-bubbles.png`, `globe-palette.png`, `globe-page-settings.png`. Keys: Ctrl+K, Esc, Alt+Left, Alt+Home, F11, Ctrl+., Ctrl+Q.

- Local model (phase 2b): `brain/local.py` is the only code that talks to Ollama. `url()` is `OLLAMA_URL`, else `OLLAMA_HOST` (scheme and port added, 0.0.0.0 means 127.0.0.1), else localhost:11434;
  `local.http` has `trust_env=False`, so proxy variables are never used, and `request()` retries a refused connection on the other spelling (localhost / 127.0.0.1) and remembers it. `stream_chat` streams
  `/api/chat`; the timeout is the wait for the next chunk: `FIRST_COLD` 60 s for the first word when the model is not in `/api/ps`, `FIRST_WARM` 15 s when it is, `GAP_SECONDS` 15 s after that (env
  `OLLAMA_FIRST_COLD`, `OLLAMA_FIRST_WARM`, `OLLAMA_GAP`); a stuck stream is cut with `abort` (socket shutdown first). Every failure is a `LocalError` with a kind (refused, timeout, stalled, missing, oom,
  ram, http, dropped, empty), the exception type, status, URL, model and seconds; `report` prints it and emits one `sys` line for the Activity page; `brain._record(..., why)` keeps the words, which
  `provider_state`, `why_down`, the Brains card and the self block show. "could not be reached" is only for a refused connection. `compact` turns a plain chat prompt (persona, memory, facts, self block) into
  the short persona + nickname + time + last 4 turns (120 characters each), about 400 tokens; tool plans and other prompts pass through. `predict_cap`: chat 200 tokens, drafts 500. `brain.preload_local()`
  runs at start (not in hybrid mode) and loads the model with keep_alive 5m when free RAM allows; `local.warming()` shows "LOCAL MODEL WARMING UP" in the classic pill and "local, warming up" in the new
  bottom panel. `python -m jarvis.doctor --ollama` makes the same call chat makes (`brain.chat_request` then `_try_ollama`). `scripts/fakes/fake_ollama.py` is a fake server on a real port;
  `scripts/ollama_check.py` covers every failure kind, the slow-first-word stream and the real Ollama when running.
- Globe interaction (phase 2b): `Stage.tick` polls `QCursor.pos()` every frame (also mouse tracking on every widget, `Shell.track`); `engaged` eases to 1 while the pointer moves and back to 0 after `IDLE_SECONDS`
  (3), which fades tilt, parallax, light, trail and repulsion and returns the globe to its slow spin. Effects: tilt, light spot (`Globe.aim`, `spot_point`, dots near it brighten), particles repelled
  (`StarField.step`) and shocked by a click (`shock`), parallax, trail (`Budget.trail` points, 0.6 s), ripples on any click, click-and-drag spins the globe (`Globe.drag`, `release`, coasting `extra`);
  a press that moves under 6 px is a click and opens the bubbles. `Budget` gained `tilt`, `trail`, `ripples`, `inertia`: reduced motion keeps only the light spot and plain dragging. Dots use
  `Globe.dot_style` over six depth buckets. Bubbles: `World` anchors travel on two ellipses round the centre (`ORBIT_SPEED`, paused while a bubble is hovered or focused), sized by `_spacing`;
  below r 50 the icon is dropped and the name centred.

- Settings (phase 3): `ui/settings_hub.py` is the Settings destination (`Shell.hub`, registered as `dash.pages["Settings"]`): General (the older page, unchanged), Profile, Memory, Customization, Models and providers.
  `Shell.run_feature` opens a section from the palette (`("page", "Settings", "<section>")`; `features.SETTINGS` lists each setting). Nothing on these pages reads or shows a key.
- Profile: `core/profile.py` saves full name, preferred name, nickname, preferences and personality in `settings.json` ("profile") and applies them to `config` with `config.set_names` (also at import, so a
  restart keeps them; an empty name returns to its `.env` value). `profile.prompt_lines()` (preferences and the personality sentence) is added to `chat_system`, `quality_system`, `cloud_system` and
  `local.short_system`; `self_block` carries the names; the globe screen's greeting (`status.greeting`) uses the nickname. `profile.listeners` fire on save.
- Memory: `memory/controls.py` (`settings.json` "memory": `paused`, per-category switches; ordinary categories on, `people` and `health` off) is checked by `facts.add` and `memory.remember`;
  `facts.secret_refusal` (secrets, numbers, addresses) is never switchable. `memory/manager.py` is one view over `facts` (memory.jsonl), `memory.db` facts, people and episodes: `entries`, `search`, `get`, `update`,
  `delete`, `clear_all`, refs like `facts:<id>`. The Memory page: pause, category switches, filter, search, table, editor, delete selected, two-click Clear all. Chats are kept separately.
- Look: `design.settings()` / `update()` / `apply()` hold the saved look (`ui2`: accent, background, globe density/size/glow, intensity, chat size and density); `design.ACCENT` is the chosen accent lifted
  with `readable` until it reads at 4.5:1 on both the page and the panel colour of the chosen background (`BACKGROUNDS`, `THEMES`, `ACCENT_PRESETS`). `design.version` bumps on every change so caches
  (`backdrop`, `glass`, bubble pixmaps, the cursor glow) rebuild; `design.listeners` run `Shell.on_look` (restyle, budget, repaint). Globe state colours come from the accent (`globe.look_for`).
  `budget(low, reduced, intensity, density)`; `pages_qss` dresses tables, text boxes and check boxes. Voice speed is `voices.speed` / `set_speed` (settings.json `voice_speed`, else `VOICE_SPEED`).
- Models: `brain/registry.py` builds the Models page from real data: `describe(pid)` (configured, key set or not, last real call from `brain.HEALTH`, manual `probe`, role from `order()` for the mode, selected model,
  capabilities, usage from `data/usage.json` and `data/traces.jsonl`, errors). Extra providers: `EXTRA_PROVIDERS=name` with `NAME_URL`, `NAME_API_KEY`, `NAME_MODEL` (OpenAI-compatible; `brain._extra_call`, inserted
  before the local model by `brain._chain`). The model picked on the page is `config.chosen(provider)` (`settings.json` "models"), used by `brain.groq_model`, `brain.openrouter_models` and `pick_ollama_model`.
  `openrouter_models()` fetches the list when asked and caches it in `data/openrouter-models.json`. `scripts/settings_check.py` includes a scan that no key appears in any UI string, log, result or saved file.

- CPU for the model: `local.Generation` wraps every local call (`brain._try_ollama`); `local.generating()` is true while one runs and `local.listeners` are told. `Dashboard.set_throttled` (both windows) makes the
  clock low power and stamps `local.state["ui_throttled_at"]`; `design.budget(busy=True)` is 15 fps, no particles and `cursor=False`, which pauses tilt, light, trail, ripples, parallax, repulsion and dragging on the globe
  (`Stage.engaged` drops to 0 at once). A user's own low power setting is left as it was. `local.log_turn` emits one `sys` Activity line per turn: prompt tokens (reported by Ollama, else estimated), time to the first
  word (warm or cold), total time, "UI throttled yes/no"; a failed turn says "no answer after N s (kind)". The line avoids the words error, failed and stopped, so the globe does not turn red. `local.LAST["turn"]` keeps it for the doctor.
- Repeated errors: `threads.add(..., error=True)` (set by `threads.is_error_reply`: the current trace is failed, or the words say so) does not append an error reply identical to the last assistant message; that message gets
  `count` and listeners hear an `update` (the chat shows "(x3)"). A good answer in between ends the run. `scripts/throttle_check.py`.

- Reply language (replaces the older `reply_hint` rules): `lang.reply_setting()` is the saved choice ('en', 'hi', 'kn' or None for automatic) in `data/settings.json` under `"language"` (`set_reply` writes it, a restart reads it;
  before this it lived only in `lang._session`, in memory). `lang.reply_language(text)` is the saved choice, else the script of the current message, so English is the default and Hindi or Kannada only when the message is in that
  script. `lang.reply_hint(text)` is exactly "Reply in <Language> only, short." and is in every prompt (`chat_system`, `quality_system`, `cloud_system`, `local.short_system`). `local.compact` drops history in any other script so an old
  Hindi conversation cannot pull the model back. `lang.label()` ("English (auto)", "English", "Hindi", "Kannada") shows in the classic pill (`REPLY ...`), the new bottom panel and Settings, Customization (Reply language).
  Direct commands (`main.DIRECT` first entries, `main.fuzzy` for typos): "speak/talk/reply/respond/answer/write in english|hindi|kannada", "switch to ...", "english only", "speak english"; they run `set_language` (mode reply),
  which saves and answers with `lang.confirmation` in that language. `tools.COMPLAINT` (in `small_talk`): "i didnt ask time", "that is not what i asked", "i said ..." are conversation, never tool requests.
- Local turns: `local.record_turn` / `recent_turns` / `average_first_word` keep the last 10 turns (numbers only) in `data/local-turns.json`; the Stats page shows the average first word over those that produced one.
  `scripts/reply_language_check.py`.
