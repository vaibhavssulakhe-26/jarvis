# Ana

A voice assistant for Linux that runs on your own laptop. Say the wake phrase, give a command in your own words, and she does it and talks back: reminders, apps, music, WhatsApp, volume, screenshots, web research, drafts and code files. Warm, a bit playful, and honest about what she can and cannot do.

Work in progress. Developed on Fedora 44 with KDE Plasma on Wayland.

## What she can do
- Reminders in natural language, announced by notification and voice
- Open apps and web apps, play music on YouTube Music
- Send WhatsApp messages to saved contacts (she reads the message back first, then types and sends it)
- Volume, screenshots, battery and system status, lock screen
- Web research that reads a few pages and summarizes them, with a saved list you can follow up on
- Drafts for emails and messages, signed with your name
- Writes code files into a project folder and opens them in your editor
- Speaks up now and then: low battery, break nudges, a joke

## How it works
- Wake word: openWakeWord, running locally ("Hey Jarvis" for now, a custom Ana word is planned)
- Speech to text: faster-whisper locally, or Groq's hosted Whisper if `ANA_STT=groq`
- Brain: a free LLM on Groq picks one action from a fixed tool list. If Groq is unavailable she falls back to a local Ollama model
- Voice: Piper, running locally

## Privacy and safety
- Only the transcribed text of a command goes to the cloud brain. With `ANA_STT=groq`, the audio of each command (after the wake word) goes to Groq too. Nothing is sent before the wake word
- The model can only choose from the tools in `ana/tools.py`. It cannot run shell commands
- Risky tools (messages, shutdown, restart, suspend) ask for a clear yes first, unless the contact is on your trusted list
- Web pages, emails and files are treated as data, never as instructions
- Secrets live in `.env`, which is never committed. Copy `.env.example` to start

## Setup
1. `uv venv --python 3.12 .venv && source .venv/bin/activate`
2. `uv pip install -r requirements.txt && uv pip install --no-deps openwakeword`
3. Copy `.env.example` to `.env` and fill it in. Get a free Groq key at console.groq.com
4. Download a Piper voice into `~/piper-voices`, and the wake word model files into `models/`
5. Run `python -m ana.main`, or `python -m ana.main --text` to type instead of speak

## Layout
- `ana/main.py` wires everything together
- `ana/ears.py` wake word, recording and speech to text
- `ana/brain.py` the prompt, the cloud brain and the local fallback
- `ana/tools.py` every action she can take, each with a risk level
- `ana/research.py` web research
- `ana/reminders.py`, `ana/voice.py`, `ana/state.py`, `ana/companion.py`, `ana/config.py`

## Known limits
- Free-tier rate limits and a CPU-only laptop mean a command takes about two to four seconds
- She cannot see the screen or click inside apps
- Linux only

## License
MIT. See LICENSE.
