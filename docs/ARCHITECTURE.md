# Jarvis architecture

Personal voice assistant for Fedora KDE Wayland. One Python package (`jarvis/`), a PyQt6 dashboard, and a local-first brain.
Numbers below were measured on the repo as of the v4 audit (phase 1).

## Entry points

| Command | What it starts |
|---|---|
| `python -m jarvis.main` | `core/main.py:main`: dashboard plus the voice loop (`--text` typed, `--no-ui` headless) |
| `python -m jarvis.scheduling.daemon` | reminders only, used by `systemd/jarvis-reminders.service` |
| `python -m jarvis.routines run\|list\|now` | routines, used by `systemd/jarvis-routines.*` |
| `python -m jarvis.doctor`, `.bench`, `.setup`, `.telegram`, `.ui.palette`, `.voice.dictate` | tools |

## Layers

Dependencies point downward. A layer may import the ones below it; the exceptions are listed under "Known cycles".

| Layer | Package | Lines | Role |
|---|---|---|---|
| UI | `ui/dashboard/`, `ui/palette.py`, `ui/ui.py` | 2900 | Qt pages, theme, chat view. `ui/ui.py` only starts the voice loop and shuts everything down |
| Logic | `core/main.py`, `brain/agent.py`, `actions/` | 9100 | Routing of a sentence, the tool registry and the 166 tools |
| Voice | `voice/` | 1700 | Wake word, VAD, listening gate, speech to text, Piper, barge-in, dictation |
| Providers | `brain/brain.py`, `brain/advanced.py` | 1500 | Groq, OpenRouter, Ollama, tiers, budget, local-first policy |
| Memory | `memory/` | 1200 | Facts, notes, chat threads, FTS5 search |
| Storage | `core/jsonfile.py`, `memory/store.py`, `core/state.py`, `data/` | | JSON files (atomic write), SQLite, the shared state file |
| Integrations | `telegram.py`, `routines/ical.py`, `actions/mail.py`, `actions/browser.py`, `holo.py`, `actions/mpvctl.py`, `platform/` | | Things outside the process. All OS commands sit in `platform/` |
| Monitoring | `scheduling/`, `traces.py`, `alerts.py`, `doctor.py`, `bench.py` | 1300 | Reminders, guard, proactive chat, traces, alerts, diagnostics |

## How a sentence flows

```
ears (wake word, VAD) -> voice/gate.judge -> stt -> main.handle
   main._handle:  stop words -> pending yes/no -> study/interview -> files choice
                  -> direct() and fast_path()      no model, no network
                  -> agent.pick(text)
                       tools matched: agent.turn  -> brain.tool_turn -> tools.execute (max 3 rounds)
                       none matched:  brain.chat  (streaming, spoken early by voice/stream)
   voice.say -> voice/speech.clean -> Piper
```

## The brain (`brain/`)

- `BRAIN_MODE=local_first` (default): `route`, `generate`, `tool_turn`, `ask`, `code` send everything to Ollama unless the request is
  advanced. Advanced means the user said so (`advanced.USER_WORDS`) or the caller marked it heavy (`advanced=True`, or `brain.code`).
- Advanced goes through `advanced.budget()` (daily cap, question under 10 left), `advanced.ambient()` (noise and failure lines stay home) and
  `advanced.cloud_view()` (trimmed context). Success is counted as `advanced` in `data/usage.json` and the reply gets tier `advanced`.
- Cloud failure or an empty budget: one spoken sentence, then the local answer.
- `hybrid` keeps the older order (Groq, OpenRouter, Ollama). `offline` never calls the cloud.
- Turn state for advanced is per thread (`advanced._t()`), reset by `brain.end_turn()`.

## The tool registry

`actions/tools.py` holds `TOOLS`, the `@tool` decorator, `TRIGGERS` and `rank_tools`. A tool is shown to the model only if it has a `TRIGGERS` entry.
The tool modules register themselves when `tools.py` imports them at its bottom. That is the one large import cycle (45 modules): each module
imports `tools` for the decorator, and `tools` imports each module to fill the registry. It is deliberate and stable; breaking it would need an explicit
`register_all()` call at startup.

## Data (`data/`, git-ignored)

`memory.db` (SQLite), `rag.db` (FTS5), `usage.json` (calls and tokens per provider and day, plus the `advanced` counter), `traces.jsonl`, `chats/`,
`reminders.json`, `settings.json` (voice, theme), `notes/`, `briefings/`, `browser-profile/`. Small JSON files go through `core/jsonfile.py`.

## Checks

`scripts/all_checks.sh` runs 59 `*_check.py` scripts, each in its own empty data, runtime and workspace folders. None needs a microphone or an account.

## Audit findings (v4 phase 1)

Verified by import graph, `vulture`, `ruff --select F`, and a word search over code, scripts, docs and systemd.

**Removed** (no references anywhere):
- `ui/ui.py`: the old holographic window (`Stage`, `Window`, `Bus`, `main`, palette and QSS, about 490 lines). The file keeps `start_core`, `shutdown_all`, `service_active`.
- `brain.think`, `brain.build_system`, `RULES`, `FORMAT`, `SPEECH`: the pre-agent tool prompt, replaced by `brain/agent.py`.
- `main.dedupe`, `modeler.have_model`, `threads.detach`, `window.global_search`.
- Unused imports (`ruff F401`).
- Two copies of the code-fence stripper, now `core/text.fence`; the hand-rolled usage writer, now `core/jsonfile`; three readers of `usage.json`, now `advanced.today`.

**Kept on purpose:**
- `scikit-learn` and `tqdm` have no import in `jarvis/`, but `openwakeword` (installed with `--no-deps`) imports both. `scipy` likewise.
- Qt overrides (`dragEnterEvent`, `dropEvent`, `sizeHint`, `mousePressEvent`) look unused to `vulture` and are called by Qt.
- `scheduling/digest.py` is still used by the daemon, briefing and focus tools.

**Open, not changed in this phase:**
- Research follow-ups ("open the third result") read `brain.NOTES`, which only `build_system` put in front of a model. The agent path never does, so those
  follow-ups have no data. Fix: add the `<web_data>` block to `agent.system_text`.
- Error handling: 111 `except Exception` and 21 handlers that do nothing (`pass` or `continue`). Most are around optional hardware or UI; they should log
  `type(e).__name__` at least.
- `brain.py` is 1290 lines and mixes provider calls, rate budgets, prompts and health tracking. Splitting it into `providers/`, `budget`, `prompts` is the
  next structural step; it touches every check, so it needs its own phase.
- 14 `ruff F` findings remain (unused locals in `focus_tools`, `companion`, `digest`, `widgets`; a shadowed `guard` in `main`; `notes` redefined in `tools`).
- Two private helpers named `_public` (`monitor.py`, `research.py`) look alike but differ.
