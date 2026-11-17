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
- Dashboard: `python -m jarvis.main` opens a dark glass HUD (icon rail with Home, Chat, Activity, Media, Code, Notes, Study, Web, Stats, Settings; a particle orb
  that reacts to listening, thinking and speaking; gauges, a live feed, a today card, provider status, a memory graph of notes). The voice loop
  runs in a background thread, so everything can also be typed and the window works with the mic off. `--no-ui` is the old headless mode,
  `--text` is typed-only in the terminal. Close hides to the tray; Quit stops mpv, the browser and child processes.
- Home shows system gauges, provider cards with last latency, memory, a large core with the J.A.R.V.I.S title, a live feed, active agents,
  a mission timeline and a voice waveform strip. The window size is remembered. Below 1 GB free memory a LOW RAM chip appears and low power is on.
- Themes: Ice (default, cyan with violet), Cyan, Amber (amber with red), Green, Red, Purple, Pink, White or a custom hue (Settings), by the top bar button, or by voice: "change theme to red",
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

## Listening in noise, chat, memory and the browser agent
- Push to talk: set `PTT_KEY` (for example `RIGHTCTRL`; needs the input group) or hold the Talk button in the window. Hold, speak, release. No wake word needed.
- Crowd mode: `CROWD_MODE=on`, the Settings checkbox, or say "crowd mode on" / "crowd mode off". Every command needs the wake word and the follow-up window stays shut.
- Recordings end after 0.8 seconds of silence and never run longer than `MAX_RECORD_SECONDS` (12). `NOISE_SUPPRESS=on` adds a light filter. `python -m jarvis.doctor` shows the
  measured noise floor and the mode; the bottom bar of the window has a mic level meter.
- Chat: the Chat page and the CHAT button (a dock on the right of every page) show one thread for typed and spoken messages, with markdown, copy buttons and streaming text.
  Drop a PDF, text or image file on it and ask a question. Chats are saved, redacted, in `data/chats/`.
- Quality mode (`QUALITY_MODE`, on by default) gives chat turns a fuller persona, 12 turns of history and up to four spoken sentences; the first sentence is spoken while the rest
  arrives. Hard questions (explain, plan, compare, debug, long ones) go to a larger Groq model (`GROQ_STRONG_MODEL`) while the free quota allows, and the feed shows which tier answered.
- Memory: Jarvis keeps durable facts you state about your projects, goals, preferences and plans in `data/memory.jsonl` (never passwords, keys, card numbers, health details or
  facts about other people). Say "what do you remember about <topic>", "show my memory" or "forget <topic>"; the Notes page lists them too.
- Browser agent: say "use the browser to find the cheapest USB cable on Amazon". It plans, then acts step by step (up to `AGENT_MAX_STEPS`, 12), reading the page's accessibility
  tree. It asks before submit, post, buy, delete, login and downloads, never types passwords or cards, and stops at a captcha. Stop it with the Stop button on the Web page,
  Ctrl+., the word "stop", or `AGENT_ABORT_KEY`.

## One brain, tools, files and the dashboard

- Obvious commands (time, date, volume, play, stop, reminders, notes and so on) run locally with no model. Everything else is one model turn that sees the recent
  conversation, the six most relevant real tools (name and one line each) and a self block built at that moment: mode, which brains answer right now, tool groups,
  your nickname, the time. The model answers or calls tools for up to three rounds (native function calling on Groq, strict JSON elsewhere).
- Truthful by construction: what Jarvis says about a tool comes from the tool's result. A failure is one plain sentence, "I tried play media, it failed because ...",
  and the model's own wording is dropped. What Jarvis runs on and what it can do is answered only from the self block; in hybrid mode it never says it is offline.
- When every cloud brain fails Jarvis says so once, with the cause and when it resets, and prefixes offline replies with "(offline)".
- No scripted filler: no start-up greeting, no jokes or motivational check-ins. The briefing states facts, makes no model call when there is nothing to say and then reads "Nothing scheduled."
- Files (read only, inside your home folder): "what is in my downloads", "list my pictures by date", "open the 4th picture in my pictures folder" (Jarvis names the file and asks yes or no first),
  "read notes.txt", "what is in the 4th picture" (vision model if `GROQ_VISION_MODEL` is set, otherwise OCR). Paths containing a word from `FILE_DENY` (default personal, .ssh, .gnupg, .env, password) are never listed, read, opened or indexed.
- "send this to my phone" is verified by reading the outbox line back and says where it was saved, and that it reaches the phone when the folder syncs. It asks for a device only when you did not say one (or set `HANDOFF_DEFAULT`).
- Everything is read and written as UTF-8, including logs, API replies and the window.

Dashboard: a thin icon rail (names in tooltips), a slim top bar with the date, time and one status pill (click it for brains, memory, alerts and the reveal switch for phone numbers and email addresses,
which are masked in every display by default), and the theme button. Home has the core as a background layer, glass panels on the left and the chat as the main panel on the right, with a card per message,
a streaming cursor, a copy button and a chip per tool call ("find file: done", "play music: failed"). Chat shows only the conversation, Activity shows routing and system messages, Code shows the build log. Other pages get a
resizable chat drawer (Ctrl+J). Text reads at 4.5 to 1 or better in every theme.

## Phone, planner, study and web helpers

### Telegram (`TELEGRAM=on`)
1. In Telegram talk to @BotFather, create a bot and copy its token into `.env` as `TELEGRAM_BOT_TOKEN`. Set `TELEGRAM=on`.
2. Start Jarvis. It prints a six digit pairing code in the terminal (and shows it under Settings, Keys). Send that code to your bot from your phone once.
   That chat becomes the owner (`data/telegram.json`). Every other chat gets no reply at all. `python -m jarvis.telegram --unpair` forgets the owner.
3. Send commands as you would type them. `/brief`, `/email`, `/tasks`, `/status` and `/stop` are shortcuts. Replies come back as text.
4. Safety: risky tools wait for a yes or no from the owner chat. Sending, deleting, powering off and installing are never run from the phone; coding and browser
   agent tasks only with `TELEGRAM_ALLOW_AGENT=on`. Messages are rate limited (`TELEGRAM_RATE`), forwarded messages are never run as commands, and what Jarvis
   logs is masked. Messages sent while Jarvis was off are dropped on start.
5. Jarvis messages you the morning brief, the email digest, failed routines (alerts) and due reminders.

### Timetable, deadlines, tasks and the brief
- `data/timetable.md` (`- Mon 09:00-10:00 | Data Structures | Room 204`) and `data/deadlines.md` (`- 2026-11-20 | Submit the DSA assignment`) are plain files you can edit.
  Say "next class", "what's today's schedule", "what's due this week", "add deadline report on friday", "add class monday 9 to 10 data structures room 204".
- "task: buy a cable" appends to `data/tasks.md`; "list tasks", "done 2", "clear done". Open tasks appear in the brief.
- The morning brief (`BRIEFING_TIME`) now has today's classes, deadline countdowns, open tasks, a study set and a one line focus suggestion. One brain call
  for the whole brief (under 800 tokens in and out), or a template without a brain. At that time it is shown on the dashboard, spoken (three sentences) and sent to Telegram.

### Email digest
- `EMAIL_DIGEST_TIME` (18:00): the last 24 hours of mail, read only, sorted into Needs attention, Good to know and Promotions. Rules first, one model call for the unclear ones,
  and mail that reads like instructions is never shown to the model. The Home card shows it, the top two are spoken, the full digest goes to Telegram. "/email" builds one now.
  (`DIGEST_TIME` is still the old weather and news digest.)

### Study from your own notes
- "quiz me from my notes on trees" uses the indexed notes and PDFs (`NOTES_DIR`, `RAG_FOLDERS`, for example your syllabus PDF). Five questions per model call, graded briefly,
  stored as Leitner cards in `data/study.json` (wrong answers come back at once, right ones after 1, 3, 7 and 14 days). "review due questions" asks up to five due cards;
  the same five are in the brief and in the Telegram brief. The Study page shows due cards and weak topics.

### Alerts
- A routine, briefing or scheduled job that fails writes a line to `data/alerts.jsonl`, shows an ALERTS chip in the top bar and messages you on Telegram. "show alerts", "clear alerts".

### Offline Wikipedia (optional)
- `pip install libzim`, then download a Wikipedia ZIM file yourself and set `OFFLINE_WIKI=/path/to/file.zim`. Nothing is downloaded for you.
  Kiwix publishes them at <https://download.kiwix.org/zim/wikipedia/>; pick a "mini" or "nopic" English file for a small download (a few hundred MB to a few GB)
  and check the size before you start. "look up photosynthesis" always uses it, "what is X" uses it while `BRAIN=offline`. The answer names the article titles.

### Websites for hackathons
- "make a website for a plant shop" has the coder agent build a static site (index.html, style.css, script.js, no build step) in `CODE_WORKSPACE`, then fixes the
  basics of accessibility (language, viewport, alt text, skip link, keyboard focus) and lists what it could not (contrast, heading order, empty links).
  "preview it" serves the folder on a free local port and opens it; "stop preview" stops it; "export it" makes a zip and prints the GitHub Pages and Netlify steps.
  Jarvis never deploys, pushes or publishes anything.

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

### How to test phases 30 and 31
- `core_check` (25 must-always-work phrases end to end with a scripted fake model, plus truthfulness, deny list, offline prefix and outage checks; the pass rate is shown on the Stats page), `encoding_check`
  (smart quotes, an em dash, Hindi and Kannada through the router, chat, logs, files, API replies and the window) and `dashboard_check` (layout, contrast, masking, separate logs, previews in `data/ui-previews/`, memory).
  By hand: ask "who are you, are you offline", "what is in my pictures folder", "open the 3rd picture in my pictures", set a wrong Groq key and watch the one-time outage line.

### How to test phases 22 to 28
Each check needs no account, microphone or network: `python scripts/<name>.py`, or `scripts/all_checks.sh` for everything.
- Telegram: `telegram_check` (fake Bot API on localhost). By hand: set the token, `TELEGRAM=on`, start Jarvis, send the printed code, then "what time is it", "/status",
  and a risky command such as "close Spotify" (it must ask yes or no). A second Telegram account must get no answer.
- Timetable and brief: `timetable_check`. By hand: "add class ...", "next class", "add deadline ... on friday", "what's due this week", then "morning briefing".
- Email digest: `digest_check` (fake mailbox with an injection mail). By hand: set the Gmail app password, say "run the email digest now" or send `/email`.
- Study from notes: `study_notes_check`. By hand: put a PDF in `RAG_FOLDERS`, "reindex my notes", "quiz me from my notes on <topic>", "review due questions".
- Alerts and tasks: `alerts_check`. By hand: break a routine (for example an unreachable mailbox), then "show alerts"; "task: test", "list tasks", "done 1".
- Offline Wikipedia: `wiki_check` (fake pack and fake libzim). By hand: set `OFFLINE_WIKI`, `python -m jarvis.doctor`, "look up photosynthesis".
- Web helper: `webproject_check`. By hand: "make a website for a bakery", "preview it", "stop preview", "export it".

## Run

```bash
python -m jarvis.main
```

Requires `.env` with API credentials. See `.env.example`.
