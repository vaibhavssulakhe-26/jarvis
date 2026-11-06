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

## Wake word

The wake phrase is "Hey Jarvis" (`WAKE_WORD=hey_jarvis`).

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
- Voices: `python scripts/get_voices.py` downloads Ryan, Joe and Alan into `models/voices`.
- New `.env` keys: `VOICE` (first-run voice), `CODE_WORKSPACE`, `CODE_PROVIDER`, `CODE_MODEL`, `BROWSER`.
- Checks: `python scripts/<name>_check.py` (no mic or accounts needed).

## Run

```bash
python -m jarvis.main
```

Requires `.env` with API credentials. See `.env.example`.
