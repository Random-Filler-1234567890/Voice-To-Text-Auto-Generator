# VoiceFlow

A hyper-personalized, context-aware voice dictation assistant for macOS -
hold a hotkey anywhere on your system, speak, and get clean, correctly
formatted text typed at your cursor. It learns your vocabulary, the names
of people you work with, and your personal facts over time, and adapts
its formatting to whatever app you're dictating into.

Lives entirely in your menu bar. No terminal required for daily use.

## Important: how this was built

This codebase was written and unit-tested in a **Linux cloud sandbox**,
not on a Mac. Every platform-independent module - configuration, the
hotkey timing state machine, the personal-memory relevance ranking, prompt
construction, the AI provider fallback chains, the clipboard-injection
logic, and the full record-transcribe-format-inject pipeline orchestration
- has a real, passing `pytest` suite (107 tests) that ran in that sandbox
and is included in `tests/`. Run it yourself any time with `pytest`.

What could **not** be built or tested here: the actual macOS `.app` bundle
(building one requires macOS + Xcode command line tools), and anything
that needs a real mic, a real global keyboard hook, real clipboard/paste
simulation, or the native menu bar UI (`rumps`/PyObjC) - those only exist
on macOS. So the very first time you build it, treat it like a normal
piece of new software: build it, actually use it for a day, and tell me
what needs fixing. It's engineered carefully and every piece of logic
that *can* be verified has been - but "verified end-to-end on a real Mac"
is a step only you can do the first time.

## What it does

- **Global hotkey dictation, anywhere.** Hold Right Option (configurable)
  and speak; release to have the cleaned-up text pasted at your cursor.
  Double-tap to start hands-free recording that keeps going after you let
  go; double-tap again to stop. Works in any app - VS Code, Slack, Gmail,
  Notes, Claude, ChatGPT, Terminal, anywhere you can paste text.
- **Context-aware formatting.** VoiceFlow detects the frontmost app (and,
  best-effort, the window/tab title) and formats accordingly: code-style
  text in your editor, casual short messages in Slack, full grammar in
  emails and docs, literal commands in a terminal, prompt-preserving
  cleanup when dictating to an AI assistant.
- **Long-term personal memory.** Say "Learn: my company is Acme Corp and
  my boss is Sarah Chen" and VoiceFlow extracts and remembers that as
  structured facts. Every future dictation automatically pulls in the
  facts, names, and vocabulary relevant to what you're saying, so it gets
  your coworkers' names, acronyms, and jargon right without you spelling
  them out again.
- **Multi-provider AI with automatic fallback.** Configure Groq (fast,
  generous free tier - recommended), OpenAI, and/or Anthropic. If one
  fails, it automatically falls through to the next, and can fall all the
  way through to a fully offline local Whisper model if you enable it.
- **Clipboard-safe.** Your existing clipboard contents are snapshotted
  before pasting and restored automatically afterward - dictation never
  destroys something you had copied.
- **Native menu bar app.** Status icon shows what it's doing (idle /
  recording / transcribing / formatting / pasting / learning). Everything
  - API keys, hotkey, mode, audio device, memory, logs - is reachable from
  the menu. No config files to hand-edit (though you can, they're plain
  JSON).

## Quick start (macOS)

You need a Mac (macOS 11+) and about five minutes. This is a **one-time**
Terminal step to produce the app - after that you never need Terminal
again.

```bash
git clone <this-repo-url> VoiceFlow
cd VoiceFlow
./build_macos_app.sh
```

The script creates a virtual environment, installs dependencies, builds
the app icon, and packages everything into `dist/VoiceFlow.app`. Then:

1. `cp -R dist/VoiceFlow.app /Applications/` (or drag it in Finder).
2. Open VoiceFlow from Applications or Spotlight.
3. macOS will ask for **Microphone**, **Accessibility**, and **Input
   Monitoring** permissions the first time - approve all three (System
   Settings -> Privacy & Security), then quit and reopen VoiceFlow once.
   The menu's "Permissions & Setup Guide..." item walks you through this
   and jumps straight to each settings pane.
4. Click the menu bar icon -> **AI Providers** -> **Set Groq API Key...**
   (get a free key at console.groq.com - it's the fastest and has the
   most generous free tier, which is why it's the default first provider).
5. Hold **Right Option** anywhere and speak. Release to paste.

If macOS refuses to open it ("cannot be opened because it is from an
unidentified developer" - expected, since this is an unsigned personal
build, not something from the App Store): right-click `VoiceFlow.app` ->
**Open** -> **Open**. You only need to do this once.

### If something goes wrong on first launch

Run it from source instead, so you get a real Python traceback in the
terminal instead of a silently-failed menu bar icon:

```bash
./run_dev.sh
```

Fix whatever the traceback shows (or send it to me), then re-run
`build_macos_app.sh` to rebuild the `.app`.

## How the hotkey works

Default key: **Right Option**. Configurable from the menu (**Hotkey ->
Key**) to Right Command, Right Control, Right Shift, Caps Lock, or F13-F19.

Three modes (**Hotkey -> Mode**):

- **Hybrid (default)** - hold past ~180ms to start hold-to-talk (release
  stops); or double-tap quickly to start hands-free "latched" recording
  that keeps going after you let go (double-tap again to stop). A single
  lone tap does nothing, so brushing the key by accident is harmless.
- **Hold-to-talk only** - classic push-to-talk, no double-tap gesture.
- **Toggle** - one tap starts, one tap stops.

Start any dictation with **"Learn: "** or **"Remember: "** to teach it a
fact instead of dictating text - e.g. "Learn: my boss is Sarah Chen and
she leads the platform team." It's extracted into structured memory and
automatically resurfaced whenever it's relevant to what you're saying.

## Configuration

Everything is also editable by hand at
`~/Library/Application Support/VoiceFlow/config.json` (menu bar app closes
over this - restart it after manual edits). Your learned memory lives
alongside it in `memory.json`, and logs in `logs/voiceflow.log` (rotated
automatically, also reachable from the menu's **View Logs**).

Notable settings:

| Key | Meaning |
|---|---|
| `providers.transcription_order` | Fallback order for speech-to-text, e.g. `["groq", "openai", "local"]` |
| `providers.formatting_order` | Fallback order for the cleanup/formatting LLM pass |
| `hotkey.hold_threshold_ms` | How long a press must last before it counts as "hold" vs. a tap |
| `hotkey.double_tap_window_ms` | Max gap between two taps to count as a double-tap |
| `formatting.learn_prefixes` | Which spoken prefixes trigger the memory-teaching flow |
| `app_profiles_overrides` | Map a bundle id to a formatting category to override the built-in mapping |
| `audio.save_recordings_for_debug` | Keep WAV files on disk for troubleshooting (off by default - audio never touches disk otherwise) |

## Offline fallback

Enable **AI Providers -> Enable Offline Fallback (faster-whisper)** in the
menu, then `pip install faster-whisper` into VoiceFlow's environment (see
`requirements.txt` - it's commented out by default because it pulls in a
sizeable ML runtime and downloads a model on first use). With it enabled,
if every cloud provider fails or you have no internet, transcription still
works fully offline (formatting/memory still need a cloud LLM key, though
- only the speech-to-text step has an offline path).

## Architecture

```
voiceflow/
  config.py            Thread-safe JSON config, dot-path access, self-healing on corruption
  state.py              Thread-safe app state machine (IDLE/RECORDING/TRANSCRIBING/FORMATTING/INJECTING/LEARNING/ERROR)
  pipeline.py            Orchestrates the full record -> transcribe -> (learn | format) -> inject flow
  logging_setup.py       Rotating file + console logging, global exception hooks
  paths.py                Central filesystem paths (~/Library/Application Support/VoiceFlow)
  main.py / app.py       Entry point + the rumps menu bar application

  hotkeys/
    state_machine.py     Pure-logic hold/toggle/double-tap-latch interaction FSM (fully unit tested)
    listener.py           pynput adapter feeding real key events into the state machine

  audio/
    recorder.py           In-memory sounddevice capture -> WAV bytes, no disk I/O on the hot path

  context/
    app_profiles.py       Bundle-id/app-name/window-title -> formatting profile mapping (pure logic)
    macos_context.py       NSWorkspace + Accessibility API adapter for the frontmost app/window

  memory/
    store.py               JSON-backed personal memory profile (facts/people/vocabulary/acronyms/corrections)
    relevance.py            Dependency-free TF-IDF cosine-similarity relevance ranking

  ai/
    providers.py            Groq/OpenAI/Anthropic HTTP clients + local faster-whisper fallback
    transcription.py        Speech-to-text fallback chain
    formatter.py             Formatting + "Learn:" fact-extraction fallback chain
    prompts.py                System prompt construction

  clipboard/
    injector.py              Copy -> paste -> timed restore, with full error handling

  ui/
    onboarding.py, permissions.py, sounds.py, launch_agent.py
                             Setup copy, System Settings deep links, sound feedback, launch-at-login

tests/                    107 pytest tests covering every module above except the four macOS-only adapters
```

## Running the test suite

Works on any platform (Linux, macOS, CI):

```bash
pip install -r requirements-dev.txt
pytest
```

## Honest limitations / what's not in scope

To set expectations correctly rather than over-promise:

- **Speaker diarization ("who's talking")** and **voice-based emotion/health
  trend detection** are genuinely hard, heavy ML problems (think
  `pyannote.audio`, large models, GPU-friendly inference) that don't fit a
  "just works, no huge downloads" personal tool. They're not implemented.
  If you want a lightweight version later (e.g. flagging a dictation as
  markedly faster/slower or shorter/longer than your rolling average as a
  crude proxy signal), that's a reasonable follow-up, not a one-shot add.
- **Common-spelling learning** happens through the explicit "Learn:"
  mechanism and the "correction" memory category, not through silent
  passive inference from every dictation - that keeps behavior
  predictable and avoids the model quietly "correcting" things you didn't
  ask it to.
- The settings UI is native macOS menu items and dialogs (`rumps`), not a
  custom-drawn preferences window - this was a deliberate reliability
  choice: it's built entirely on rumps' well-documented, stable API
  surface, versus hand-rolled AppKit `NSWindow` code that couldn't be
  tested here at all before reaching you.
- Distribution is unsigned (no Apple Developer Program membership was
  available to sign/notarize this from here), so the standard
  right-click-Open dance is needed once. Nothing else changes.
