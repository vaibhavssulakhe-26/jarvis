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
- Browser control: "go to github", "search cats on YouTube", "click About us", "scroll down", "read this page", "go back", "new tab",
  "close tab". Own profile, no typing into secret fields, risky clicks and downloads wait for a yes
- Dashboard: `python -m jarvis.main` opens a dark glass HUD (sidebar with Home, Media, Code, Notes, Study, Web, Stats, Settings; a particle orb
  that reacts to listening, thinking and speaking; gauges, a live feed, a today card, provider status, a memory graph of notes). The voice loop
  runs in a background thread, so everything can also be typed and the window works with the mic off. `--no-ui` is the old headless mode,
  `--text` is typed-only in the terminal. Close hides to the tray; Quit stops mpv, the browser and child processes.
- Themes: Cyan, Green, Amber, Red, Purple, Pink, White or a custom hue (Settings), by the top bar button, or by voice: "change theme to red",
  "next theme", "random theme". Optional state colours and hue cycling. The choice is saved in `data/settings.json`.
- Low power mode (Settings, or automatic below 1.5 GB free): 15 fps, 40 points, no rings. Animation stops while the window is hidden or minimised.
- "Jarvis stats": last test pass rate, average tokens and which brain answered how often

## Wake word

The wake phrase is "Hey Jarvis" (`WAKE_WORD=hey_jarvis`).

To see how well "Jarvis" or "hello Jarvis" is picked up, run with `WAKE_DEBUG=1`: the best wake score is printed whenever it passes 0.15,
even below the threshold (`WAKE_THRESHOLD`, default 0.4). Interrupting speech uses its own level (`BARGE_THRESHOLD`, default threshold plus 0.3).

A custom wake model goes in the `models/` folder. Any extra `.onnx` file there that is not one of the bundled ones (alexa, hey_jarvis,
hey_mycroft, hey_rhasspy, timer, weather) or the shared helper models is loaded next to `hey_jarvis`, so both wake it.

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
2. `python scripts/eval_phrases.py` sends 30 phrases through the router with a mocked brain and saves `data/eval/<date>.json`
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
