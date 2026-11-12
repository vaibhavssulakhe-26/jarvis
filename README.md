# Jarvis

A personal voice assistant that runs locally on Linux. Talk to it, it listens, thinks, and acts.

## What it does

- Wakes on voice command (say "Hey Jarvis")
- Transcribes speech using a cloud STT service
- Thinks using a cloud brain with a local offline fallback
- Speaks responses using a local TTS engine
- Takes screenshots and sends them via WhatsApp
- Sets reminders, checks battery and system status, controls volume
- Opens apps and URLs, searches the web, writes files
- Remembers context across a conversation
- Finds files and summarises documents, keeps notes, morning digest, page monitors, email triage
- Focus guard: opt-in, warns once when I drift into games or social feeds ("turn on focus guard")
- Translate ("translate good morning to Hindi"), explain an error or debug code from the clipboard
- Clipboard monitor (opt-in), research mode with cited notes, send text or files to my phone or laptop
- Voice switching: "change your voice", "use a male voice", "use the British voice", "what voice are you using"
- Coding: "build me a todo app", "add a footer to index.html", "find bugs in app.py", "run it" (asks first)
- Laptop control: "open the browser", "close Spotify" (asks first), "switch to Chrome", "minimise this", "brightness up",
  "open github.com", "search python decorators"
- Research: "research graph theory", "I need help with X", "how do I X", then "show me" to open the sources
- Command palette: a small box for typed commands ("open palette")
- Play: "play a video on dsa", "play a lofi song" picks one itself; "next" or "another one" moves to the next result
- Hindi and Kannada: "listen in Hindi", "reply in Kannada", "listen in auto". Hindi is spoken; Kannada is shown and copied
- Say "stop", "quiet" or "enough" to cut Jarvis off; "Hey Jarvis, stop" works while it talks, and the window has a STOP button
- With mpv installed, videos and music play in one player: "next", "pause", "resume", "stop playing", "louder", "skip forward", "go back"
- Friendly chat, and optional check-ins when I have been quiet (`PROACTIVE`, "be chattier", "stop talking for two hours")
- Stop control: "stop", "stop music" and "quiet" quit or pause mpv whenever it runs; the STOP button, Ctrl+. and `voice --stop` also kill it.
  While music plays the mic only goes to speech recognition after the wake word. mpv is killed on exit.
- Nickname: `USER_NICKNAME` (default `USER_NAME`) is what Jarvis calls me in greetings and replies
- Notes and PDF search: "search my notes for X", "what did I write about X", "summarise <file>", "reindex my notes". SQLite FTS5, no embeddings;
  three chunks go to the model and the answer names the file
- Study buddy: "quiz me on trees" (arrays, linked lists, trees, graphs, DP), "teach me about recursion", "my weak topics",
  "what's next on my roadmap", "mark arrays done", "log today", "how was my week"
- Focus: "start focus 25", "break", "stop focus", "good morning" (date, reminders, next roadmap item, streak), "note: buy a cable"
- Screen and dictation: "read my screen" (OCR with tesseract), hold-to-talk dictation into the focused window (`DICTATE_KEY`)
- Coding agent: "build me a flask app" plans, writes, runs and fixes (4 tries) in `CODE_WORKSPACE/<name>`; "run it", "stop it",
  "fix the last error", "add dark mode to <project>", "explain this file", "git init this project"
- Confirmations take loose answers ("yes close it", "confirm") and drop the rest of the sentence. Searches use DuckDuckGo (`BROWSER_SEARCH`); a captcha stops the
  command and Jarvis offers the normal browser. "What can you do" and "can you code" are answered from the tool list, never guessed.
- Browser control: "go to github", "search cats on YouTube", "click About us", "scroll down", "read this page", "go back", "new tab",
  "close tab". Own profile, no typing into secret fields, risky clicks and downloads wait for a yes
- Dashboard: `python -m jarvis.main` opens a dark glass HUD (sidebar with Home, Media, Code, Notes, Study, Web, Stats, Settings; a particle orb
  that reacts to listening, thinking and speaking; gauges, a live feed, a today card, provider status, a memory graph of notes). The voice loop
  runs in a background thread, so everything can also be typed and the window works with the mic off. `--no-ui` is the old headless mode,
  `--text` is typed-only in the terminal. Close hides to the tray; Quit stops mpv, the browser and child processes.
- Home shows system gauges, provider cards with last latency, memory, a large core with the J.A.R.V.I.S title, a live feed, active agents,
  a mission timeline and a voice waveform strip. The window size is remembered. Below 1 GB free memory a LOW RAM chip appears and low power is on.
- Themes: Cyan (default), Green, Amber, Red, Purple, Pink, Ice, White or a custom hue (Settings), by the top bar button, or by voice: "change theme to red",
  "next theme", "random theme". Optional state colours and hue cycling. The choice is saved in `data/settings.json`.
- Low power mode (Settings, or automatic below 1.5 GB free): 15 fps, 40 points, no rings. Animation stops while the window is hidden or minimised.
- "Jarvis stats": last test pass rate, average tokens and which brain answered how often
- Live answers: weather, news, scores and prices ("what's the weather in Pune", "latest news on ISRO") are looked up with DuckDuckGo plus
  trafilatura, no browser window; the top three pages are summarised in one sentence and the sources are named. A browser opens only for "open ..."
- `BRAIN=offline` never calls a cloud provider (or cloud speech recognition); the mode is shown in the dashboard top bar
- Routines (`data/routines.md`): a morning briefing (unread mail, top 10 by importance, today's calendar, reminders, next roadmap item, focus
  status), a nightly inbox triage and a nightly notes reindex run on a schedule and catch up after the laptop was off. Say "morning briefing",
  "what's important in my email", "what's on my calendar", "add routine at 9 pm reindex my notes", "list routines", "run the morning briefing now",
  "draft a reply to Priya" (saved in Gmail Drafts and the clipboard, never sent)
- "Run diagnostics" (or `python -m jarvis.doctor`) checks the mic, wake model, keys, Ollama, mpv, tesseract, browser, voice, memory and venv
- "Show my failures" lists the last ten failed or corrected requests from `data/traces.jsonl`; `python -m jarvis.bench` times the 30 eval phrases

## Job-search helper (optional, `JOBS=on`)

Everything is local files in `data/` (git-ignored): `jobs.json` (tracker), `profile.md` (your base resume text, which you write), `job-suggestions.json`,
`interview-log.json`. Nothing is applied for, sent or scraped. Email and job text are data, never instructions.

- Tracker: "add job Acme as data analyst" (several-word companies: "add job Goldman Sachs, business analyst"; add "DA resume" or "applied" anywhere),
  "update Acme to interview", "what did I apply to this week", "what needs a follow-up" (applied or interviewing jobs a week after applying, or on the
  date set). Each job has company, role, resume type (BA, DA, OA or PA: business, data, operations, product analyst), location, link, date applied,
  status (saved, applied, interview, offer, rejected), notes and a follow-up date. The Jobs page shows a table with a status filter and counts per
  status and resume type.
- "Analyse this job" (clipboard text, or paste it): title, company, location, skills asked for, sponsorship and years-of-experience phrases, which skills
  match `profile.md`, which are missing, a one-line fit note and the best resume type. One brain call under 800 tokens; without a brain the rules
  give the same fields. Only the extracted fields and a short, masked resume summary are sent; `JOBS_USE_CLOUD=false` keeps even that on the laptop.
- "Draft a follow-up email to Acme" and "draft a cover letter for this job" go to the clipboard and Gmail Drafts. You send them.
- The morning briefing lists recruiter and application-system mail first. Suggested tracker changes (for example "Globex looks like rejected") wait for
  "apply job updates" and a yes.
- "Practice interview for data analyst": five spoken questions one at a time, two lines of feedback after each answer, weak areas logged;
  "stop" ends it, "what are my weak interview areas" reads the log back.

## Setup wizard and profiles

`scripts/install.sh` installs the system packages (dnf, apt or Homebrew, asking first) and starts `python -m jarvis.setup`, which detects the
system, checks Python and the tools, creates `.venv` and installs the requirements, downloads the Piper voice you pick, asks for API keys with hidden
input (saved in `.env`, mode 600, never printed) and finishes with `python -m jarvis.doctor`. Options: `--yes`, `--no-venv`, `--voice NAME`, `--profile NAME`.

Two people can share one machine: set `JARVIS_PROFILE=name` (environment or `.env`). A profile reads `.env.<name>` first (so its `USER_NAME` and
`USER_NICKNAME` win), and keeps its own `data/profiles/<name>/` (notes, reminders, briefings, memory, browser profile), state file and runtime folder.
`python -m jarvis.setup --profile sister` creates the profile's `.env.sister`.

## macOS (not yet run on a Mac)

All operating-system calls go through `jarvis/platform/` (`linux.py`, `mac.py`). The Mac backend was written from the tools' documentation and has
not been run on a Mac. A feature with no Mac backend says "... is not supported on this system" instead of crashing.

- Install: `brew install python@3.11 mpv tesseract ollama portaudio`, then `pip install -r requirements.txt` (pynput replaces evdev) and
  `pip install --no-deps openwakeword==0.3.0`, or just run `scripts/install.sh`.
- Expected to work: the brain (Groq, OpenRouter, Ollama), text mode, reminders, notes and PDF search, study, routines and the briefing, email,
  the calendar link, live answers, the coding helper, the dashboard, Piper voices, mpv playback, `pbcopy`/`pbpaste` clipboard, `open`,
  `screencapture`, notifications, volume and sleep/lock through AppleScript and `pmset`, launchd for the schedule and login item.
- Untested: all of the above on a real Mac; microphone permission prompts; wake word latency; the window title, close and minimise helpers (need the
  Accessibility permission for the terminal); hold-to-talk dictation and pasting (pynput, needs Accessibility and Input Monitoring); the global
  stop key; Music app media keys; AppleScript window switching.
- Not supported on a Mac yet: brightness, do-not-disturb during focus sessions, playerctl-style media keys for other players, the focus guard's
  window reading may be limited.
- Scheduling: `systemd/` is for Linux; on a Mac the setup wizard's launchd job (`com.jarvis.*.plist` in `~/Library/LaunchAgents`) does the same.
- Data lives in `~/Library/Application Support/Jarvis/` on a Mac and in the repository's `data/` on Linux.

GitHub Actions (`.github/workflows/checks.yml`) runs `scripts/ci_run.sh` on Ubuntu and macOS with Python 3.11: the checks in `scripts/ci_checks.txt`,
with `QT_QPA_PLATFORM=offscreen`. A check marked `linux` there is skipped on macOS with a message.

## Routines, briefing and calendar

`data/routines.md` is created on first use and is plain text, one routine per line: `- 08:00 | morning briefing | build the morning briefing`.
`briefing-time` in the time column means `BRIEFING_TIME` from `.env` (default 08:00). Instructions Jarvis understands: briefing, triage (read only),
reindex. Edit the file by hand or say "add routine ...".

The briefing is saved to `data/briefings/<date>.md`, shown on the Home card, and spoken (three sentences at most) on "good morning" or at the first
start of the day. It makes at most one brain call under 800 tokens; with no brain it uses a plain template. Email is read over IMAP with a read-only
select and `BODY.PEEK`: nothing is ever sent, deleted, moved or marked read, and email text is treated as data (anything that reads like an instruction
is kept out of the model prompt). "Draft a reply to <sender>" writes the reply, appends it to Gmail Drafts, copies it and says so. You send it yourself.

The calendar is a private iCal link in `CALENDAR_ICS_URL` (Google Calendar: Settings, your calendar, "Secret address in iCal format"). It is fetched
with a plain GET, cached for 15 minutes and never printed or logged. No OAuth and no write access.

Scheduling when the app is closed (user level systemd; the timer also fires after a sleep or a power-off thanks to `Persistent=true`):

```bash
mkdir -p ~/.config/systemd/user && cp systemd/jarvis-routines.* ~/.config/systemd/user/
systemctl --user daemon-reload && systemctl --user enable --now jarvis-routines.timer
python -m jarvis.routines list      # run | list | now <name>
```

The running app also runs missed routines at startup and checks every five minutes; a file lock keeps the two from running one routine twice.

## Wake word

The wake phrase is "Hey Jarvis" (`WAKE_WORD=hey_jarvis`).

To see how well "Jarvis" or "hello Jarvis" is picked up, run with `WAKE_DEBUG=1`: the best wake score is printed whenever it passes 0.15,
even below the threshold (`WAKE_THRESHOLD`, default 0.4). Interrupting speech uses its own level (`BARGE_THRESHOLD`, default threshold plus 0.3).

A custom wake model goes in the `models/` folder. Any extra `.onnx` file there that is not one of the bundled ones (alexa, hey_jarvis,
hey_mycroft, hey_rhasspy, timer, weather) or the shared helper models is loaded next to `hey_jarvis`, so both wake it.

Saying the name last works too ("play something Jarvis"): while idle Jarvis keeps four seconds of audio, and when the wake word fires it also
transcribes speech that came just before it. Use `WAKE_DEBUG=1` to see the scores, and say a sentence ending in the wake word a few times to tune
`WAKE_THRESHOLD`. While Jarvis talks or music plays, the microphone is compared with the level it learned for its own output; only a clearly louder
voice is listened to, and only a stop word ("stop", "quiet", "enough", "pause") is acted on. Anything written to traces, notes or the conversation log
first has emails, phone numbers, long digit strings, keys and passwords masked (`jarvis/redact.py`).

Keyboard shortcuts for the player: `python -m jarvis.actions.mpvctl --pause`, `--stop` and `--next`. In KDE System Settings, Shortcuts,
Add New, Command or Script, use `/home/paradox/Documents/JARVIS/.venv/bin/python -m jarvis.actions.mpvctl --pause` (working folder: the repo),
then pick a key for it. `--next` hands the request to the running Jarvis, so Jarvis must be running.

## Stack

Python, PyQt6, faster-whisper, openWakeWord, Piper TTS, Ollama

## Structure
jarvis/
core/ main loop, config, state
brain/ cloud and local reasoning
voice/ wake word, speech-to-text, text-to-speech
memory/ short-term and long-term memory
actions/ tools — volume, screenshots, messaging, apps
scheduling/ reminders and background daemon
research/ web search
ui/ PyQt6 interface

## Setup notes

- `pip install -r requirements.txt`, then `pip install --no-deps openwakeword==0.3.0`.
- `kdotool` is needed for the focus guard. `wl-clipboard` is needed for the clipboard features.
- Palette shortcut: in System Settings, Shortcuts, add a command `/home/<me>/Documents/JARVIS/.venv/bin/python -m jarvis.ui.palette`
  (run from the project folder) and bind a key.
- Hand-off: set `HANDOFF_DIR` to a folder that Syncthing or KDE Connect shares with the phone.
- Voices: `python scripts/get_voices.py` downloads Ryan, Joe, Alan and the Hindi voice Pratham into `models/voices`.
  If the network blocks it, the script prints the links to download by hand.
- Film-style voice: put `jarvis.onnx` and `jarvis.onnx.json` in `models/voices` yourself, then say "use the jarvis voice".
  The `dataset` field inside the `.onnx.json` must match the file name. Voice files are git-ignored.
- Kannada has no speech voice yet (the only ONNX build of Meta MMS Kannada fails to run on onnxruntime, and the
  original needs torch). Kannada replies appear on screen, go to the clipboard, and Jarvis says so in English.
  No online speech service is used.
- Speech recognition with `STT=groq` uses `STT_MODEL` (default whisper-large-v3) and detects the language itself.
  The local fallback is the multilingual `STT_LOCAL_MODEL` (default `small`).
- Proactive chat sends nothing online by itself: lines come from a local list, plus at most one small brain call every four hours.
- New `.env` keys: `USER_NICKNAME`, `NOTES_DIR`, `RAG_FOLDERS`, `FOCUS_MUTE_NOTIFICATIONS`, `DICTATE_KEY`, `BROWSER_HEADLESS`, `BROWSER_LITE`,
  `BROWSER_CHANNEL`, `BROWSER_IDLE_MINUTES`, `BROWSER_DOWNLOADS`. All are in `.env.example` with safe defaults.
- Screen reading needs `sudo dnf install tesseract`. Without it Jarvis says so and "describe my screen" still uses the vision model.
- Dictation reads the keyboard through evdev, which needs `sudo usermod -aG input $USER` (then log out and in). Without that, bind
  `.venv/bin/python -m jarvis.voice.dictate --once` to a KDE shortcut: it records until you stop talking and pastes the text.
- Browser control uses Playwright (`pip install playwright`) with Google Chrome; without Chrome run `playwright install chromium`.
  Its profile is `data/browser-profile`, separate from your own.
- Other new `.env` keys: `VOICE` (first-run voice), `CODE_WORKSPACE`, `CODE_PROVIDER`, `CODE_MODEL`, `BROWSER`, `STUDY_CHANNELS`,
  `STT_MODEL`, `STT_LOCAL_MODEL`, `STT_LANGUAGE` (default `en`), `PROACTIVE`, `PLAYER` (`mpv` or `browser`).
- Long replies (drafts, code, lists) are shown on screen and copied instead of being read out. A KDE shortcut for
  `.venv/bin/python -m jarvis.voice.voice --stop` gives a global stop key.
- Checks: `python scripts/<name>_check.py` (no mic or accounts needed).

## How to test

1. `scripts/all_checks.sh` runs every `*_check.py` that needs no microphone and prints one line each (`mic_check.py` is interactive).
2. `python -m jarvis.bench` times the same 30 phrases (add `--live` to use the real brain, which spends tokens) and saves
   `data/eval/bench-<date>.json`; the Stats page shows the latest. `python scripts/replay_failures.py` replays failed or corrected requests.
   `python scripts/eval_phrases.py` sends 30 phrases through the router with a mocked brain and saves `data/eval/<date>.json`
   (`--scratch` keeps the result out of `data/`). Then say or type "jarvis stats".
3. Dashboard without a display: `QT_QPA_PLATFORM=offscreen python scripts/dashboard_check.py`. Text mode without a microphone: `python -m jarvis.main --text`, then try "quiz me on trees", "note: test", "start focus 1",
   "search my notes for graphs", "go to example.com".
4. With a microphone, use the list in `NOTES.md` ("Needs a real microphone").
5. One feature at a time: `rag_check`, `study_check`, `focus_check`, `screen_check`, `coder_build_check` (needs network for the Flask
   install), `browser_check` (needs Chrome and Playwright), `stop_check`, `stats_check`.

## Run

```bash
python -m jarvis.main
```

Requires `.env` with API credentials. See `.env.example`.
