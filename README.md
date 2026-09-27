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
logic, meeting-notes chunking, and the full pipeline orchestration - has a
real, passing `pytest` suite (213 tests) that ran in that sandbox and is
included in `tests/`. Run it yourself any time with `pytest`.

What could **not** be built or tested here: the actual macOS `.app` bundle,
and anything that needs a real mic, a real global keyboard hook, real
clipboard/paste simulation, or the native menu bar UI/floating indicator
(`rumps`/PyObjC) - those only exist on macOS. The first bug report you
sent back (the onboarding alert reopening in a loop) was exactly this kind
of thing: logic that looked right on paper but had never run against the
real rumps event loop. It's fixed now (see **Changelog** below) and I've
gone through the rest of the app looking for the same class of mistake,
but "verified end-to-end on a real Mac" is still a step only you can fully
do - especially the new floating listening indicator, which is flagged
below as the single riskiest piece of UI code in the app.

## Changelog

**Round 7 (the actual, actual root cause of the sounddevice/PortAudio crash):**

- **Found and fixed the real bug behind "cannot load library ...
  python39.zip/_sounddevice_data/portaudio-binaries/libportaudio.dylib".**
  Round 6's fix (surfacing the real error instead of a generic message)
  worked exactly as intended - it's the only reason this precise error was
  visible at all. That error revealed the actual root cause: `sounddevice`'s
  macOS wheel ships PortAudio's binary in a **separate top-level package**
  called `_sounddevice_data`, not inside `sounddevice` itself. `setup.py`
  only told py2app to bundle `sounddevice` as a real unzipped directory -
  it had never heard of `_sounddevice_data`, so it silently zipped that
  package (dylib included) into `python39.zip`. macOS's `dlopen()` cannot
  load a shared library from inside a zip archive, full stop - so the app
  built, launched, and looked fine, and only failed the instant something
  tried to actually open the microphone. Fixed with one line: added
  `"_sounddevice_data"` to `setup.py`'s `OPTIONS["packages"]`. Added
  `tests/test_setup_packages.py` so this exact line can never be quietly
  reverted or lost in a future edit.
- **`build_macos_app.sh` now checks the *frozen* app for this whole class of
  bug, not just the dev virtualenv.** The Round 6 self-test ran
  `import sounddevice` inside `.venv`, which was always going to pass -
  that's not where the bug lives. The bug only exists inside py2app's
  frozen bundle layout. The build script now opens the built
  `python39.zip` directly after packaging and scans it for any `.dylib`/
  `.so` file that shouldn't be there, failing the build immediately (with
  the exact offending path printed) instead of producing an app that looks
  fine until you try to use the microphone.

**Round 6 (the actual "sounddevice not available" error, one-command reinstall, in-app updates):**

- **Fixed a real bug: the exact reason sounddevice failed to load was being
  silently discarded.** "Microphone Test Failed: sounddevice is not
  available on this device/installation" was the *entire* message -
  there was no way to tell whether that meant a missing library, a wrong
  CPU-architecture wheel, or something else, because the original
  `ImportError`/`OSError` was caught and thrown away rather than kept.
  Fixed so the real underlying error is now included, and the build
  script (see next point) catches this specific failure with a targeted
  fix suggestion instead of it only surfacing later, mid-use.
- **`build_macos_app.sh` now explicitly verifies the audio backend loads**
  (`import sounddevice; sounddevice.query_devices()`), not just that
  VoiceFlow's own code imports - the two are different: your code can
  import fine while the *native* PortAudio library it depends on fails to
  load, which is exactly what "sounddevice not available" means. If this
  check fails, the script now prints your Mac's processor architecture
  and the specific `pip uninstall`/`pip install --force-reinstall` command
  to try - a CPU-architecture mismatch (Apple Silicon vs. Intel wheels,
  often via a Rosetta-emulated Python) is the most common cause.
- **Added a one-command full uninstall + reinstall** - see below.
- **Added an "Update VoiceFlow..." button** (in both the window and the
  menu) that opens a visible Terminal window and runs the updater for you
  - no more manually opening Terminal and remembering the path. It finds
  your source checkout automatically (`build_macos_app.sh` now records
  where it was run from) and falls back to `~/VoiceFlow` if that record
  isn't there yet.

**Round 5 (a real window, and the microphone-permission mystery):**

- **Added a real window.** Menu -> "Open VoiceFlow Window..." (it also
  opens automatically on launch now) gives you a persistent, native window
  showing live status, Microphone/Accessibility permission state, one-click
  buttons for the actions you'd otherwise dig through the menu for, and a
  proper text field for your Groq key - instead of transient notifications
  you might miss. Every control in it duplicates something already in the
  status-bar menu, which stays fully intact as a fallback: if this window
  ever fails to open for any reason, nothing else about the app is
  affected. **Honest flag:** this is a bigger, more custom piece of
  hand-written AppKit code than anything else in the app (a full window
  with buttons and text fields, versus the HUD's single floating panel),
  written as conservatively as I could manage - plain frame layout, no
  Auto Layout, no custom drawing - but it is the least-proven code here.
  If it misbehaves, the menu still does everything it always did.
- **Added a startup microphone pre-flight check.** VoiceFlow now attempts
  to briefly open the microphone right after launching, instead of only
  the first time you try to dictate - this gives macOS's permission
  prompt the earliest possible chance to appear, and the window's
  Microphone row reflects the real result immediately rather than sitting
  on "not checked yet."
- **On "it never asked for microphone access" specifically:** this is very
  likely a stuck macOS permission decision from an earlier build, not
  something a code change can fix by itself - see **If the mic still
  won't prompt** below for the exact command to reset it.

**Round 4 (found the menu, but mic/Meeting Notes/API key were still flaky):**

- **Fixed a real bug: Meeting Notes was writing to `~/Documents/VoiceFlow
  Notes/`**, and macOS treats Documents (like Desktop and Downloads) as a
  specially-protected folder requiring its own separate permission prompt
  - one VoiceFlow never declared or requested. Writing there without it
  raises a silent `PermissionError`, which is exactly the "weird bug noise
  and then nothing" - that beep is VoiceFlow's own error sound, played
  right after that exception got caught. Moved the default location to
  `~/Library/Application Support/VoiceFlow/Meeting Notes/`, next to
  everything else VoiceFlow already has unprompted access to. The failure
  notification also now shows the *actual* error message instead of a
  generic one, so if something like this happens again, you can just read
  it to me instead of describing a sound effect.
- **Hardened the "Save"/"Learn" buttons on the API key and Teach-a-Fact
  dialogs.** They previously required both "a button was clicked" AND "the
  text changed" before saving; now they save based on the text alone. If
  the reported "I put in a key and it didn't work" was this dialog
  silently discarding a valid entry, it no longer can be.
- **Added a "Test Microphone..." item** under the Audio menu - runs a
  1.5-second recording completely independent of AI keys, the hotkey, or
  anything else, and reports the exact peak audio level it heard (or the
  exact error if it couldn't open the microphone at all). This is the
  fastest way to find out whether the mic/permission layer itself is
  working, in isolation from everything downstream of it.
- Still want to know why the Microphone permission prompt never appeared
  for you at all originally - if "Test Microphone" doesn't trigger it
  either, that's the next real clue; see **Where to find VoiceFlow** and
  the troubleshooting note there.

**Round 3 (the actual root cause of "nothing happens"):**

Found it. It wasn't a crash at all - it was a packaging setting
(`LSUIElement`) that made VoiceFlow behave as a *regular* foreground app
instead of a menu-bar-only one. That meant every launch put "VoiceFlow" in
bold at the **top-left** of the screen next to the Apple logo - the normal
spot for whatever app is currently active - with an essentially empty
default menu, since that's not where rumps puts anything. The real, fully
working menu was sitting the whole time in the status bar at the
**top-right** (a small microphone icon among your WiFi/battery/clock
icons), which is easy to miss when a bold "VoiceFlow" label at the
top-left is confidently telling you to look there instead. Fixed by
setting `LSUIElement: True`, which is the standard, documented way rumps
apps (and every other menu-bar-only utility - Bartender, and almost
certainly Wispr Flow itself) are supposed to be packaged. The tradeoff:
**VoiceFlow no longer has a Dock icon** - it lives only in the menu bar
now, which is both the correct behavior for this category of app and the
only way to remove the confusing dead-end menu for good. See
**Where to find VoiceFlow** below.

**Round 2 (reliability hardening, after "nothing happens when I open it"):**

Your report that a fully clean reinstall still did nothing on launch was
the most important signal I've gotten so far, because a silent failure
with zero error text is the single hardest thing to diagnose blind. Rather
than guess again, I made three structural changes that target exactly that
failure mode, whatever its exact cause turns out to be:

- **`main.py` now catches everything.** Any failure at all while starting
  up - anywhere, for any reason - writes a full error report to
  `~/Library/Application Support/VoiceFlow/logs/crash.log` and pops up a
  native macOS alert telling you so. "Nothing happens" should no longer be
  possible even if there's still a bug somewhere: you'll now see *what*
  broke instead of silence.
- **Every optional feature added last round (the floating indicator,
  Meeting Notes, Recent Dictations, usage stats) is now individually
  fault-isolated.** If any single one of them fails to load for any reason
  (a PyObjC version mismatch, anything), the rest of the app - including
  core dictation - still starts up fine with just that one feature quietly
  disabled, instead of the whole app refusing to launch over it.
- **The build script now tests itself before saying "done."** It verifies
  the code imports cleanly, then actually launches the built `.app` and
  confirms it's still running a few seconds later, *before* telling you
  the build succeeded. `update_macos_app.sh` only reports success if this
  self-check passed - it will no longer say "Done!" over a broken build
  the way it did before.
- Also added: audio-quality-aware notifications (an actionable message
  when it detects near-silence or clipping instead of just failing
  quietly), and relaxed several exact dependency version pins that could
  fail to install on a newer Python/macOS than this was written against.

**Round 1 (feature round, after the alert-loop bug):**

- **Fixed:** the "Welcome to VoiceFlow" popup that kept reopening and
  blocked the app from being usable. Root cause: an internal timer meant
  to fire once was actually a *repeating* timer, so the alert reappeared
  every ~1 second forever.
- **Added: Quick Setup.** Menu -> AI Providers -> Quick Setup opens Groq's
  free key page in your browser, then prompts you to paste the key in, and
  validates it live against Groq's API with a real pass/fail message. One
  key covers both transcription and formatting; see **How the AI actually
  works** below.
- **Added: floating listening indicator**, like Wispr Flow's - a small
  pill appears near the bottom of your screen while VoiceFlow is
  listening/thinking and disappears the instant it's done. Toggle it off
  from the menu if it ever misbehaves.
- **Added: Meeting Notes mode** - menu -> "Start Meeting Notes" for
  continuous, hands-free transcription during a meeting or lecture. It
  keeps recording in ~20s chunks in the background, cleans each one up
  (filler words removed) and appends it with a timestamp to a running
  Markdown file (later moved out of `~/Documents` - see Round 3 below), then adds an AI-written
  summary + action items when you stop.
- **Added: "Edit:"/"Rewrite:" voice command.** Copy some text, say
  "Edit: make this more formal" (or any instruction), and VoiceFlow
  rewrites whatever's on your clipboard and pastes the result back.
- **Added: Recent Dictations** menu (click any of your last 8 dictations
  to copy it back to the clipboard) and a **usage stats** line (words
  dictated, estimated time saved).
- **Added:** `update_macos_app.sh` - one command to pull the latest code,
  rebuild, and relaunch. See **Updating** below.

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
- **Floating listening indicator.** A small pill near the bottom of the
  screen shows when VoiceFlow is listening/transcribing/pasting, like
  Wispr Flow's orb, then disappears. Toggleable from the menu.
- **Meeting Notes mode.** One click starts continuous, hands-free
  transcription for a whole meeting or lecture - no holding anything down.
  Produces a running, cleaned-up Markdown transcript with an AI summary +
  action items at the end.
- **"Edit:"/"Rewrite:" voice command.** Copy any text, speak an
  instruction, get it rewritten and pasted back - polish an email,
  simplify a paragraph, change the tone, without touching the keyboard.
- **Recent Dictations + usage stats.** Recall and recopy any of your last
  8 dictations from the menu; see a running count of words dictated and
  estimated time saved.
- **Native menu bar app + a real window.** Status icon shows what it's
  doing (idle / recording / transcribing / formatting / pasting /
  learning / editing / in a meeting). A persistent window (opens
  automatically, or via "Open VoiceFlow Window..." in the menu) shows live
  permission status and gives one-click access to the most-used actions;
  everything else - hotkey, memory, audio device, history, logs - is
  reachable from the menu. No config files to hand-edit (though you can,
  they're plain JSON).

## Where to find VoiceFlow

**There is still no Dock icon** - VoiceFlow is a menu-bar-only app, not a
regular foreground one (see the Round 3 changelog entry for why that
matters). But there is now a real window: it should **open automatically**
the first time VoiceFlow launches. If you don't see it (or you closed it),
look for a small microphone icon (🎙) in the macOS **status bar - the
strip at the top-RIGHT of your screen**, in the same row as your WiFi,
battery, and clock icons - and click **"Open VoiceFlow Window..."** at the
top of its menu. That same menu (Start Dictation, AI Providers, Memory,
everything) is still there too and still fully functional - the window is
additive, not a replacement.

If you don't see the icon at all, check the little `⌃`/`>>` overflow
chevron near the clock - macOS hides menu-bar icons there when the bar
gets crowded.

The window's Permissions section shows live Microphone/Accessibility
status and has a one-click "Test Mic" button - that's the fastest way to
confirm the rest of the app is actually working, and it doesn't need an
API key or the hotkey to work first.

### If the mic still won't prompt for permission

If VoiceFlow has never once shown you the "VoiceFlow would like to access
the microphone" system dialog - not during setup, not during Test Mic, not
ever - the most likely explanation is that an **earlier build already
recorded a decision** for it (macOS remembers permission grants/denials
per app identity, and that record isn't cleared by deleting the app or
even by wiping `~/Library/Application Support/VoiceFlow`). Reset it
explicitly:

```bash
tccutil reset Microphone com.voiceflow.app
tccutil reset Accessibility com.voiceflow.app
tccutil reset ListenEvent com.voiceflow.app   # Input Monitoring
```

Then quit and reopen VoiceFlow - macOS should prompt fresh. You can also
check current state directly in **System Settings -> Privacy & Security ->
Microphone** (and Accessibility, and Input Monitoring) - if VoiceFlow is
listed there but unchecked, just check it; if it's not listed at all, the
app has never successfully asked, which the `tccutil reset` + relaunch
above should fix.

## Quick start (macOS)

You need a Mac (macOS 11+) and about five minutes. This is a **one-time**
Terminal step to produce the app - after that you never need Terminal
again. Two commands, run one at a time:

```bash
git clone https://github.com/random-filler-1234567890/voice-to-text-auto-generator.git VoiceFlow
cd VoiceFlow
```

```bash
./build_macos_app.sh
```

That second command does the whole build **and checks its own work**: it
installs everything into a private virtual environment, verifies the code
actually imports cleanly, packages `dist/VoiceFlow.app`, then launches
that app for a few seconds to confirm it stays running - before it ever
tells you it succeeded. If any of that fails, it stops and prints exactly
what went wrong instead of a false "done."

If it reports success, VoiceFlow is already running. From there:

1. **Move it into Applications** so it stays put:
   ```bash
   cp -R dist/VoiceFlow.app /Applications/ && killall VoiceFlow
   open /Applications/VoiceFlow.app
   ```
2. macOS will ask for **Microphone**, **Accessibility**, and **Input
   Monitoring** permissions the first time - approve all three (System
   Settings -> Privacy & Security), then quit and reopen VoiceFlow once.
   The menu's "Permissions & Setup Guide..." item walks you through this
   and jumps straight to each settings pane.
3. Click the menu bar icon -> **AI Providers** -> **Quick Setup...** - it
   opens Groq's free key page in your browser, then asks you to paste the
   key in, and confirms it works before you continue. Takes under a
   minute; see **How the AI actually works** below for why this step can't
   be skipped entirely.
4. Hold **Right Option** anywhere and speak. Release to paste.

If macOS refuses to open it ("cannot be opened because it is from an
unidentified developer" - expected, since this is an unsigned personal
build, not something from the App Store): right-click `VoiceFlow.app` ->
**Open** -> **Open**. You only need to do this once.

### If the build script reports a failure

It'll tell you which check failed (import error vs. the app not staying
running) and point you at two places: a saved crash report at
`~/Library/Application Support/VoiceFlow/logs/crash.log`, and:

```bash
./run_dev.sh
```

`run_dev.sh` runs VoiceFlow straight from source, attached to your
terminal, so any error prints right there instead of vanishing into a
double-clicked app with no console. Copy whatever it prints back to me (or
fix it yourself, if the traceback makes the problem obvious) - that's the
single most useful piece of information for tracking down anything that
isn't already caught by the checks above.

## How the AI actually works

VoiceFlow itself doesn't include a speech-to-text or language model - no
personal app safely can, since that requires either a huge on-device model
or a hosted backend with someone else's API key baked in (which anyone
could extract from the app and abuse on your bill). So VoiceFlow calls a
cloud AI provider directly, using **your own** API key, for two things:

1. **Transcription** (audio -> raw text) - via Groq's or OpenAI's Whisper
   API, or a fully offline local model if you enable it.
2. **Formatting** (raw text -> clean, context-aware text) - via a fast
   chat model (Groq/OpenAI/Anthropic).

**You only need one key** - Groq's free tier covers both steps, which is
why "Quick Setup" only asks for a Groq key. Adding OpenAI/Anthropic keys
later is optional extra redundancy (automatic fallback if Groq is ever
down), not a requirement. The key is stored only in
`~/Library/Application Support/VoiceFlow/config.json` and is sent only to
that provider's API, directly from your Mac - it never passes through any
server of mine.

## Updating

VoiceFlow doesn't auto-update (that needs a signed app + an update server,
out of scope for a personal build) - but updating is one command:

```bash
cd VoiceFlow   # wherever you cloned it
./update_macos_app.sh
```

This pulls the latest code, quits the running app, rebuilds and
self-tests it (same checks as `build_macos_app.sh` - import check + audio
backend check + a real launch-and-stay-running check), replaces
`/Applications/VoiceFlow.app`, and reopens it. It only prints "Done!" if
that self-test actually passed - if anything's broken it stops and tells
you what, instead of claiming success over a build that doesn't work.
Your config, memory, history, and stats all live outside the `.app`
bundle (in `~/Library/Application Support/VoiceFlow/`), so updating never
touches or resets any of that.

**Even more convenient:** click the mic icon in the menu bar (or open the
main window) -> **"Update VoiceFlow..."**. It runs the exact same script
for you in a visible Terminal window, so you never have to type the `cd`/
`./update_macos_app.sh` yourself. It finds your source checkout
automatically as long as you've built at least once since this button was
added; if it can't find it, it tells you the manual command to run instead
of guessing wrong.

### Full uninstall + reinstall

If something's stuck and you want a completely clean slate, this single
block does the whole thing - kills the running app, removes the installed
app, all of VoiceFlow's saved data, the login-item helper, and any old
source checkout, then clones fresh and rebuilds:

```bash
killall VoiceFlow 2>/dev/null; \
rm -rf /Applications/VoiceFlow.app \
       ~/Library/Application\ Support/VoiceFlow \
       ~/Library/LaunchAgents/com.voiceflow.app.plist \
       ~/VoiceFlow && \
cd ~ && \
git clone https://github.com/random-filler-1234567890/voice-to-text-auto-generator.git VoiceFlow && \
cd VoiceFlow && \
./build_macos_app.sh && \
cp -R dist/VoiceFlow.app /Applications/ && \
killall VoiceFlow 2>/dev/null; \
open /Applications/VoiceFlow.app
```

This is safe to run even if nothing was installed yet (each removal is a
no-op on files that don't exist) - it's the same "one command" whether
you're updating, starting over, or setting up for the very first time.

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

Start with **"Edit: "** or **"Rewrite: "** followed by an instruction to
rewrite whatever's currently on your clipboard instead - e.g. copy a
paragraph, say "Edit: make this more concise," and the rewritten version
gets pasted back where your cursor is.

For continuous transcription without holding anything (a meeting, a
lecture, a long brainstorm), use **menu -> Start Meeting Notes** instead
of the hotkey - see **Meeting Notes** below.

## Meeting Notes

Click the menu bar icon -> **Start Meeting Notes**. VoiceFlow records
continuously in ~20-second chunks (configurable via `meeting.chunk_seconds`),
transcribes and lightly cleans up each one (filler words removed, but
nothing summarized away), and appends it with a timestamp to a Markdown
file in `~/Library/Application Support/VoiceFlow/Meeting Notes/Meeting
YYYY-MM-DD HH-MM.md` as the meeting happens - so even if something crashes
mid-meeting, everything up to that point is already safely on disk. Click
**Stop Meeting Notes** when you're done; VoiceFlow adds an AI-written
summary and action-items section to the top of the file and opens it for
you (which is also the easiest way to find the file, if you don't want to
navigate there by hand). It's deliberately **not** in `~/Documents` - that
folder requires a separate macOS permission VoiceFlow doesn't request,
which would otherwise make Meeting Notes fail silently with a permission
error. Set `VOICEFLOW_MEETING_NOTES_DIR` as an environment variable if you
want it saved somewhere else instead.

Known limitation: there's a brief (typically 1-3 second) gap between
chunks while the previous one transcribes, since chunks are processed
sequentially rather than while the next one records - a deliberate
simplicity/robustness tradeoff over trying to record and transcribe
concurrently. You'll never lose more than one API round-trip's worth of
audio at a time, and it doesn't affect the normal hold-to-talk hotkey flow
at all.

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
| `formatting.edit_prefixes` | Which spoken prefixes trigger the clipboard rewrite flow |
| `app_profiles_overrides` | Map a bundle id to a formatting category to override the built-in mapping |
| `audio.save_recordings_for_debug` | Keep WAV files on disk for troubleshooting (off by default - audio never touches disk otherwise) |
| `meeting.chunk_seconds` | How long each Meeting Notes recording chunk is (default 20s) |
| `meeting.generate_summary` | Whether to add an AI summary/action-items section when a meeting ends |
| `ui.show_hud` | Whether the floating listening indicator appears |

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
  state.py              Thread-safe app state machine (IDLE/RECORDING/TRANSCRIBING/FORMATTING/INJECTING/LEARNING/EDITING/MEETING/ERROR)
  pipeline.py            Orchestrates record -> transcribe -> (learn | edit | format) -> inject
  meeting.py             Meeting Notes: chunked recording, cleanup, running Markdown file, summary
  history.py              Rolling JSON history of recent dictations (recall/recopy from the menu)
  stats.py                 Usage counters + estimated time-saved heuristic
  logging_setup.py       Rotating file + console logging, global exception hooks
  paths.py                Central filesystem paths (~/Library/Application Support/VoiceFlow)
  main.py                 Entry point - a paranoid try/except around everything that writes
                          a crash log + shows a native alert on any startup failure (see below)
  app.py                   The rumps menu bar application; optional features (history/stats/
                          meeting/HUD) import defensively so one broken module can't sink the app

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
    providers.py            Groq/OpenAI/Anthropic HTTP clients + local faster-whisper fallback + key validation
    transcription.py        Speech-to-text fallback chain
    formatter.py             Formatting, fact-extraction, rewrite, and meeting-summary fallback chain
    prompts.py                System prompt construction

  clipboard/
    injector.py              Copy -> paste -> timed restore, with full error handling

  ui/
    hud.py                   Floating listening indicator (AppKit) - see Honest limitations below
    main_window.py            The persistent status/settings window (AppKit) - the largest, least-proven
                             piece of hand-written UI code in the app; see Honest limitations below
    status_text.py            Pure-logic text formatting for the window/menu (fully unit tested)
    onboarding.py, permissions.py, sounds.py, launch_agent.py
                             Setup copy, System Settings deep links, sound feedback, launch-at-login

tests/                    211 pytest tests covering every module above except the macOS-only adapters
                          (hud.py, main_window.py's AppKit calls, listener.py, macos_context.py,
                          injector.py's real backends, app.py)
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
- **`ui/main_window.py` and `ui/hud.py` are real, hand-written AppKit
  code** - a titled window with buttons/text fields, and a borderless
  floating panel, respectively - and both are the kind of code most likely
  to behave differently on a real display than expected, since neither
  could be executed here before reaching you. The original plan was to
  avoid this category of code entirely and lean on rumps' well-documented
  menu/dialog primitives instead; the window exists anyway because
  notifications-only turned out to be genuinely confusing in practice, and
  a persistent window was worth the added risk once that was clear. Both
  are written as conservatively as I can manage (plain frame layout, no
  Auto Layout, no custom drawing beyond the HUD's simple rounded
  background) and both are defensive (a failure disables that one piece
  rather than crashing the app) and additive (the status-bar menu still
  does everything either of them do, and keeps working even if one of
  them doesn't). If either misbehaves, that's real signal worth reporting
  back, not a sign the rest of the app is broken too.
- Meeting Notes records in sequential chunks, not continuously overlapping
  ones - see the known limitation noted in **Meeting Notes** above.
- Distribution is unsigned (no Apple Developer Program membership was
  available to sign/notarize this from here), so the standard
  right-click-Open dance is needed once. Nothing else changes.
- **On "verified end-to-end on a real Mac":** I genuinely cannot run this
  app myself. What I can do, and have done as thoroughly as the
  environment allows: a 183-test suite covering every line of decision
  logic that doesn't require a real display; a build script that now
  actually launches the finished `.app` and confirms it stays running
  before declaring success; and a crash handler that guarantees any
  remaining failure shows you the real error instead of nothing. If
  something still breaks after all of that, the fastest path to a fix is
  always the same: run `./run_dev.sh` and send me exactly what it prints -
  that's real signal, where "it doesn't work" isn't.
