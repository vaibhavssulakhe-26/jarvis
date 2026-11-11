# Jarvis

Personal voice assistant for Fedora KDE Wayland. PyQt6 window, openWakeWord, faster-whisper, Piper,
Groq as the brain, OpenRouter as the first fallback and Ollama as the offline fallback.

## Running
- `python -m jarvis.main` from the repo root, inside `.venv`. Never `python jarvis/main.py`: the package uses relative imports.
- `python -m jarvis.main --text` to type commands instead of speaking.
- `python -m jarvis.scheduling.reminders list` prints pending reminders.

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
  characters stay on screen, are copied, and Jarvis says "Done, it's on your screen and copied." Four or five sentences are cut
  to three. A tool that must be read in full returns `speech.Full(text)` (file read aloud, short clipboard, the digest).
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
- Follow-up window: after a reply `Ears._after` keeps listening for `FOLLOWUP_SECONDS` (default 10) with no wake word; thanks / that's all /
  bye / stop listening close it. It stays shut while `mpvctl.playing()` or playerctl reports playback.
- Speech recognition: `stt.transcribe` returns "" for clips under 0.4 s or too quiet and for known made-up transcripts (`is_hallucination`).
  `STT_HINTS` words go into the prompt.
- Capabilities: `actions/capabilities.py` answers "what can you do" / "help" from `TOOLS`; spoken summary, full list on screen.
- Stop control: `main._handle` first checks `procs.alive()` ("stop the app", "stop it" when nothing is speaking), then `stop_media` ("stop",
  "stop music", "quiet", "enough" quit mpv, "pause" pauses it, only if `mpvctl.running()`), then the speech stop words. `mpvctl.stop` also kills a stuck
  mpv and removes the socket; it runs from atexit, SIGTERM, the window's quit and the STOP key (`main.check_stop_key` polls `stop_at`). While media
  plays `Ears._idle` never records without the wake word.
- Nickname: `USER_NICKNAME` (default `USER_NAME`) becomes `config.PET_NAME`, which every greeting already uses.
- Rate limits: when Groq and OpenRouter both answer 429 in one `brain.route`, it says so once and skips the cloud for `OFFLINE_SECONDS` (60).
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
