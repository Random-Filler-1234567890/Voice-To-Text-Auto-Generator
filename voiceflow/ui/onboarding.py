"""Static copy shown in the guided permissions/setup flow."""

WELCOME_MESSAGE = """Welcome to VoiceFlow!

Before it can listen system-wide and type for you, macOS needs you to grant \
three permissions. VoiceFlow will open each settings pane for you - just \
tick the checkbox next to VoiceFlow (or your terminal, if running from \
source) in each one:

1. Microphone - so VoiceFlow can hear you.
2. Accessibility - so VoiceFlow can simulate the paste keystroke and read \
the frontmost app/window for context-aware formatting.
3. Input Monitoring - so VoiceFlow can detect your global hotkey anywhere \
on the system.

After granting each one, you may need to quit and reopen VoiceFlow once \
for macOS to apply it. Then use "Quick Setup" to add a free API key and \
you're ready to dictate anywhere - just hold your hotkey (Right Option by \
default) and speak.
"""

NO_PROVIDER_MESSAGE = """VoiceFlow needs one API key to transcribe and format your speech - \
that's the only setup step, and it takes under a minute.

Click OK, and VoiceFlow will open Groq's free key page in your browser (fast, \
generous free tier, no credit card) and then ask you to paste the key in. \
That's it - one key covers both transcription and formatting.
"""

QUICK_SETUP_NOTIFICATION = (
    'Click the mic icon in your menu bar, then "AI Providers" -> "Quick Setup..." '
    "to add a free API key and start dictating in under a minute."
)

HOTKEY_HELP = """Hold your hotkey down and speak - release to transcribe and paste \
(hold-to-talk).

Or double-tap it quickly to start hands-free recording that keeps going \
after you let go - double-tap again to stop and paste.

Start a sentence with "Learn: " (or "Remember: ") to teach VoiceFlow a fact \
about yourself instead of dictating text - e.g. "Learn: my company is Acme \
Corp and my boss is Sarah Chen." It'll remember that and use it to get \
names, jargon, and spelling right in future dictations.

Copy some text, then say "Edit: " or "Rewrite: " followed by an instruction \
(e.g. "Edit: make this more formal") to have VoiceFlow rewrite whatever's on \
your clipboard and paste the result back - handy for polishing something \
you already wrote.

Use "Start Meeting Notes" from the menu for continuous, hands-free \
transcription during a meeting or lecture - it keeps recording in the \
background and builds a running, cleaned-up Markdown transcript (with an \
optional AI summary at the end) instead of pasting anything.
"""
