# Ana

Personal voice assistant for Fedora KDE Wayland. PyQt6 window, openWakeWord, faster-whisper, Piper,
Groq as the brain, OpenRouter as the first fallback and Ollama as the offline fallback.

## Running
- `python -m ana.main` from the repo root, inside `.venv`. Never `python ana/main.py`: the package uses relative imports.
- `python -m ana.main --text` to type commands instead of speaking.
- `python -m ana.scheduling.reminders list` prints pending reminders.

## Dependencies
- `requirements.txt`, plus `openwakeword` installed with `--no-deps`.
- `psutil` for system status (memory, processor load, temperature).
- No APScheduler: reminders, including repeating ones, run on the one-second polling thread in `ana/scheduling/reminders.py`.
- System tools: `wpctl` (volume), `spectacle` (screenshots), `wl-paste` / `wl-copy` (clipboard).
  `scrot`, `gnome-screenshot`, `xclip` and `xsel` are used only as fallbacks.

## Configuration
All settings and keys come from `.env` (see `.env.example`), read in `ana/core/config.py`. Nothing is hardcoded.
- `GROQ_MODEL` text brain, `GROQ_VISION_MODEL` model used for reading the screen.

## How a command flows
`ears.py` hears it, `main.handle` tries `main.fast_path` (short unambiguous commands, no network), otherwise
`brain.think` picks an action from the registry in `tools.py`, and `main.execute` runs it. Tools register with
the `@tool` decorator; modules with their own tools are imported at the bottom of `tools.py`.

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

## Conventions
- No docstrings that restate the function name, no banner comments, no emoji.
- Tools return one short sentence to speak, and raise `ToolError` with a speakable message on failure.
- Do not edit `.env` or anything under `data/` by hand; test against a scratch copy of `reminders.FILE`.
