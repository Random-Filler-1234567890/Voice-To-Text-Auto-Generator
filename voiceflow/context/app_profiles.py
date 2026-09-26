"""Maps the frontmost application to a formatting profile.

This is pure logic (no macOS API calls) so it can be exhaustively unit
tested. ``macos_context.py`` is the thin OS-facing layer that gathers the
raw ``(bundle_id, app_name, window_title)`` tuple this module consumes.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass


class AppCategory(enum.Enum):
    CODE = "code"
    TERMINAL = "terminal"
    CHAT_CASUAL = "chat_casual"
    EMAIL_FORMAL = "email_formal"
    DOCUMENT_FORMAL = "document_formal"
    NOTES = "notes"
    AI_PROMPT = "ai_prompt"
    BROWSER_GENERIC = "browser_generic"
    DEFAULT = "default"


@dataclass(frozen=True)
class AppProfile:
    category: AppCategory
    display_name: str
    formatting_instructions: str


_PROFILE_BY_CATEGORY: dict[AppCategory, AppProfile] = {
    AppCategory.CODE: AppProfile(
        AppCategory.CODE,
        "Code editor",
        "The user is dictating inside a code editor. If they are describing code, "
        "output it as a fenced Markdown code block with the right language tag. If "
        "they are dictating a comment, docstring, or commit message, use plain text "
        "with correct technical terminology and exact casing for identifiers, "
        "framework names, and file paths. Do not add unrelated commentary.",
    ),
    AppCategory.TERMINAL: AppProfile(
        AppCategory.TERMINAL,
        "Terminal",
        "The user is dictating into a terminal/shell. Output ONLY the literal "
        "command or text to run - no Markdown, no code fences, no explanations, "
        "no trailing punctuation unless it's part of the command syntax.",
    ),
    AppCategory.CHAT_CASUAL: AppProfile(
        AppCategory.CHAT_CASUAL,
        "Chat",
        "The user is sending a casual chat message (Slack/Discord/iMessage/etc). "
        "Keep it short, conversational, and keep their contractions and tone. "
        "Light punctuation only - do not make it sound like formal writing, and "
        "do not add a greeting or sign-off.",
    ),
    AppCategory.EMAIL_FORMAL: AppProfile(
        AppCategory.EMAIL_FORMAL,
        "Email",
        "The user is composing an email. Apply full grammar correction and "
        "professional sentence structure. Preserve any greeting or sign-off they "
        "dictated; do not invent one they didn't imply. Use proper paragraph "
        "breaks for distinct thoughts.",
    ),
    AppCategory.DOCUMENT_FORMAL: AppProfile(
        AppCategory.DOCUMENT_FORMAL,
        "Document",
        "The user is writing formal document prose (Word/Pages/Google Docs). "
        "Apply full grammar and punctuation correction, proper paragraphing, and "
        "a polished, formal register while strictly preserving their meaning.",
    ),
    AppCategory.NOTES: AppProfile(
        AppCategory.NOTES,
        "Notes",
        "The user is taking quick personal notes. Be concise. If they listed "
        "multiple distinct items or steps, format as a Markdown bullet or "
        "numbered list. Preserve names, numbers, and facts with high precision - "
        "do not paraphrase specifics away.",
    ),
    AppCategory.AI_PROMPT: AppProfile(
        AppCategory.AI_PROMPT,
        "AI assistant",
        "The user is dictating a prompt to an AI assistant (Claude/ChatGPT/Gemini). "
        "Preserve every instruction, constraint, and nuance exactly - do not "
        "shorten or soften requirements. Only clean up grammar, filler words, and "
        "run-on sentences so the prompt reads clearly.",
    ),
    AppCategory.BROWSER_GENERIC: AppProfile(
        AppCategory.BROWSER_GENERIC,
        "Browser",
        "The user is dictating into a web page of unknown type. Use clear, "
        "moderately formal prose with correct grammar and punctuation as a safe "
        "default.",
    ),
    AppCategory.DEFAULT: AppProfile(
        AppCategory.DEFAULT,
        "Default",
        "Clean up filler words and grammar while strictly preserving the user's "
        "meaning and tone. Use plain prose with normal sentence punctuation.",
    ),
}

# Built-in bundle-id -> category mapping for common macOS apps. Users can
# add/override entries via config's ``app_profiles_overrides`` (bundle_id ->
# category name string), which is merged in ahead of these defaults.
BUILTIN_BUNDLE_ID_MAP: dict[str, AppCategory] = {
    "com.microsoft.VSCode": AppCategory.CODE,
    "com.apple.dt.Xcode": AppCategory.CODE,
    "com.jetbrains.pycharm": AppCategory.CODE,
    "com.jetbrains.intellij": AppCategory.CODE,
    "com.sublimetext.4": AppCategory.CODE,
    "com.github.atom": AppCategory.CODE,
    "dev.zed.Zed": AppCategory.CODE,
    "com.apple.Terminal": AppCategory.TERMINAL,
    "com.googlecode.iterm2": AppCategory.TERMINAL,
    "net.kovidgoyal.kitty": AppCategory.TERMINAL,
    "io.alacritty": AppCategory.TERMINAL,
    "com.tinyspeck.slackmacgap": AppCategory.CHAT_CASUAL,
    "com.hnc.Discord": AppCategory.CHAT_CASUAL,
    "com.apple.MobileSMS": AppCategory.CHAT_CASUAL,
    "net.whatsapp.WhatsApp": AppCategory.CHAT_CASUAL,
    "com.microsoft.teams2": AppCategory.CHAT_CASUAL,
    "com.apple.mail": AppCategory.EMAIL_FORMAL,
    "com.microsoft.Outlook": AppCategory.EMAIL_FORMAL,
    "com.readdle.smartemail-Mac": AppCategory.EMAIL_FORMAL,
    "com.microsoft.Word": AppCategory.DOCUMENT_FORMAL,
    "com.apple.iWork.Pages": AppCategory.DOCUMENT_FORMAL,
    "com.apple.Notes": AppCategory.NOTES,
    "notion.id": AppCategory.NOTES,
    "md.obsidian": AppCategory.NOTES,
    "net.shinyfrog.bear": AppCategory.NOTES,
    "com.electron.claude": AppCategory.AI_PROMPT,  # Claude desktop app
    "com.openai.chat": AppCategory.AI_PROMPT,  # ChatGPT desktop app
    "com.google.Chrome": AppCategory.BROWSER_GENERIC,
    "com.apple.Safari": AppCategory.BROWSER_GENERIC,
    "org.mozilla.firefox": AppCategory.BROWSER_GENERIC,
    "company.thebrowser.Browser": AppCategory.BROWSER_GENERIC,  # Arc
}

# Case-insensitive substring fallback when a bundle id isn't in the table
# above (used for apps we don't know the exact bundle id of, or when only
# the display name is available).
_NAME_KEYWORD_MAP: list[tuple[str, AppCategory]] = [
    ("code", AppCategory.CODE),
    ("xcode", AppCategory.CODE),
    ("pycharm", AppCategory.CODE),
    ("intellij", AppCategory.CODE),
    ("sublime", AppCategory.CODE),
    ("webstorm", AppCategory.CODE),
    ("terminal", AppCategory.TERMINAL),
    ("iterm", AppCategory.TERMINAL),
    ("kitty", AppCategory.TERMINAL),
    ("alacritty", AppCategory.TERMINAL),
    ("slack", AppCategory.CHAT_CASUAL),
    ("discord", AppCategory.CHAT_CASUAL),
    ("messages", AppCategory.CHAT_CASUAL),
    ("whatsapp", AppCategory.CHAT_CASUAL),
    ("telegram", AppCategory.CHAT_CASUAL),
    ("teams", AppCategory.CHAT_CASUAL),
    ("mail", AppCategory.EMAIL_FORMAL),
    ("outlook", AppCategory.EMAIL_FORMAL),
    ("word", AppCategory.DOCUMENT_FORMAL),
    ("pages", AppCategory.DOCUMENT_FORMAL),
    ("notes", AppCategory.NOTES),
    ("notion", AppCategory.NOTES),
    ("obsidian", AppCategory.NOTES),
    ("bear", AppCategory.NOTES),
    ("claude", AppCategory.AI_PROMPT),
    ("chatgpt", AppCategory.AI_PROMPT),
    ("gemini", AppCategory.AI_PROMPT),
    ("perplexity", AppCategory.AI_PROMPT),
    ("chrome", AppCategory.BROWSER_GENERIC),
    ("safari", AppCategory.BROWSER_GENERIC),
    ("firefox", AppCategory.BROWSER_GENERIC),
    ("arc", AppCategory.BROWSER_GENERIC),
    ("edge", AppCategory.BROWSER_GENERIC),
]

# Window-title substring heuristics, checked only when the frontmost app is
# a generic browser - lets us tell Gmail apart from Google Docs apart from
# claude.ai even though they're all "Chrome".
_TITLE_KEYWORD_MAP: list[tuple[str, AppCategory]] = [
    ("gmail", AppCategory.EMAIL_FORMAL),
    ("google docs", AppCategory.DOCUMENT_FORMAL),
    ("docs.google.com", AppCategory.DOCUMENT_FORMAL),
    ("claude", AppCategory.AI_PROMPT),
    ("chatgpt", AppCategory.AI_PROMPT),
    ("chat.openai.com", AppCategory.AI_PROMPT),
    ("gemini", AppCategory.AI_PROMPT),
    ("perplexity", AppCategory.AI_PROMPT),
    ("slack", AppCategory.CHAT_CASUAL),
    ("notion.so", AppCategory.NOTES),
    ("github.com", AppCategory.CODE),
]


def _category_from_string(value: str) -> AppCategory | None:
    try:
        return AppCategory(value)
    except ValueError:
        return None


def get_profile(
    bundle_id: str | None,
    app_name: str | None,
    window_title: str | None = None,
    overrides: dict[str, str] | None = None,
) -> AppProfile:
    """Resolve the best-matching :class:`AppProfile` for the frontmost app.

    Resolution order: user override (by bundle id) -> built-in bundle id
    table -> app-name keyword match -> (if it's a browser) window-title
    keyword match -> default.
    """
    overrides = overrides or {}
    bundle_id = bundle_id or ""
    app_name_lower = (app_name or "").lower()
    window_title_lower = (window_title or "").lower()

    if bundle_id in overrides:
        category = _category_from_string(overrides[bundle_id])
        if category is not None:
            return _PROFILE_BY_CATEGORY[category]

    if bundle_id in BUILTIN_BUNDLE_ID_MAP:
        category = BUILTIN_BUNDLE_ID_MAP[bundle_id]
        # Even for a known-browser bundle id, prefer a window-title match.
        if category == AppCategory.BROWSER_GENERIC and window_title_lower:
            title_match = _match_title_keywords(window_title_lower)
            if title_match is not None:
                return _PROFILE_BY_CATEGORY[title_match]
        return _PROFILE_BY_CATEGORY[category]

    for keyword, category in _NAME_KEYWORD_MAP:
        if keyword in app_name_lower:
            if category == AppCategory.BROWSER_GENERIC and window_title_lower:
                title_match = _match_title_keywords(window_title_lower)
                if title_match is not None:
                    return _PROFILE_BY_CATEGORY[title_match]
            return _PROFILE_BY_CATEGORY[category]

    return _PROFILE_BY_CATEGORY[AppCategory.DEFAULT]


def _match_title_keywords(window_title_lower: str) -> AppCategory | None:
    for keyword, category in _TITLE_KEYWORD_MAP:
        if keyword in window_title_lower:
            return category
    return None
