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
for macOS to apply it. Then set an API key under "AI Providers" and you're \
ready to dictate anywhere - just hold your hotkey (Right Option by \
default) and speak.
"""

NO_PROVIDER_MESSAGE = """VoiceFlow needs at least one AI provider to transcribe and format \
your speech.

Add a free Groq API key (fast + generous free tier - recommended) or an \
OpenAI/Anthropic key from the "AI Providers" menu, then try again.
"""

HOTKEY_HELP = """Hold your hotkey down and speak - release to transcribe and paste \
(hold-to-talk).

Or double-tap it quickly to start hands-free recording that keeps going \
after you let go - double-tap again to stop and paste.

Start a sentence with "Learn: " to teach VoiceFlow a fact about yourself \
instead of dictating text - e.g. "Learn: my company is Acme Corp and my \
boss is Sarah Chen."
"""
