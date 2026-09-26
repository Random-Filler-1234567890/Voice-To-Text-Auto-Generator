"""System prompt construction for the formatting and fact-extraction LLM calls."""

from __future__ import annotations

import json
import re

from voiceflow.context.app_profiles import AppProfile

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def build_formatting_system_prompt(
    app_profile: AppProfile,
    memory_snippets: list[str],
    remove_filler_words: bool = True,
    auto_punctuate: bool = True,
    preserve_tone: bool = True,
) -> str:
    """Build the system prompt for the raw-transcript -> polished-text pass.

    The prompt is intentionally explicit and constrained: return ONLY the
    final text, nothing else, so the caller never has to strip
    conversational wrapper text like "Here's the corrected version:" out
    of the model's response.
    """
    lines = [
        "You are VoiceFlow, a real-time dictation formatting engine. You receive a "
        "raw, unpunctuated speech-to-text transcript and must output ONLY the "
        "cleaned-up final text the user wants typed at their cursor. Never add "
        "commentary, explanations, quotation marks around the output, or phrases "
        "like 'Here is the text'. Output nothing but the final text itself.",
        "",
        "Core rules:",
        "- Preserve the user's exact meaning, intent, and every factual detail. "
        "Never invent information, never drop requirements or specifics.",
    ]
    if preserve_tone:
        lines.append("- Preserve the user's tone and register; do not make casual speech overly formal.")
    if remove_filler_words:
        lines.append(
            "- Remove verbal filler ('um', 'uh', 'like', 'you know', false starts, "
            "self-corrections) so the result reads as clean, intentional writing."
        )
    if auto_punctuate:
        lines.append(
            "- Add correct punctuation, capitalization, and sentence boundaries - the "
            "input transcript has none."
        )
    lines.append(
        "- If the user dictated explicit formatting instructions as part of the "
        "speech itself (e.g. 'new paragraph', 'bullet point'), apply them structurally "
        "rather than transcribing the instruction words literally."
    )

    lines += [
        "",
        f"Current application context: {app_profile.display_name}.",
        app_profile.formatting_instructions,
    ]

    if memory_snippets:
        lines += [
            "",
            "The user has taught you the following facts about themselves - use them "
            "to get names, spellings, acronyms, and terminology exactly right. Only "
            "apply ones that are actually relevant to this transcript; ignore the rest:",
        ]
        for snippet in memory_snippets:
            lines.append(f"- {snippet}")

    return "\n".join(lines)


FACT_EXTRACTION_SYSTEM_PROMPT = """You are VoiceFlow's memory extraction engine. The \
user has dictated a "Learn:" command to teach you a durable fact about themselves, \
their vocabulary, or people/organizations they work with.

Extract every distinct, atomic fact from their statement and return STRICT JSON only, \
with no markdown fences and no commentary, matching exactly this schema:

{"facts": [{"category": "<one of: fact, person, vocabulary, acronym, correction, preference>", "text": "<the fact, written as a standalone third-person sentence>"}]}

Category guide:
- "person": facts about a specific named individual (coworker, boss, friend, family).
- "vocabulary": a specialized/industry term, product name, or jargon and what it means.
- "acronym": an acronym/initialism and its expansion.
- "correction": a spelling/pronunciation correction ("X should always be spelled Y").
- "preference": a stated personal preference for how VoiceFlow should behave.
- "fact": anything else durable and factual about the user's life/work.

Rewrite each fact as a clear, self-contained sentence (do not just repeat their raw \
words if they were a sentence fragment). Split compound statements into separate \
fact objects. If nothing extractable is present, return {"facts": []}.
"""


def build_fact_extraction_user_message(raw_learn_statement: str) -> str:
    return raw_learn_statement.strip()


def strip_prefix(transcript: str, prefixes: list[str]) -> tuple[bool, str]:
    """Return ``(matched, remainder)`` if the transcript opens with one of ``prefixes``.

    Matching is case-insensitive and tolerant of the leading prefix being
    immediately followed by whitespace or a colon-space, since Whisper's
    punctuation around the spoken prefix is unpredictable (it might render
    "Learn:" as "learn:", "Learn ", or even drop the colon entirely).
    """
    stripped = transcript.strip()
    lower = stripped.lower()
    for prefix in prefixes:
        prefix_norm = prefix.rstrip(":").strip().lower()
        for candidate in (f"{prefix_norm}:", f"{prefix_norm} "):
            if lower.startswith(candidate):
                return True, stripped[len(candidate):].strip()
        if lower == prefix_norm:
            return True, ""
    return False, stripped


def strip_learn_prefix(transcript: str, learn_prefixes: list[str]) -> tuple[bool, str]:
    """Return ``(is_learn_command, remainder)``. See :func:`strip_prefix`."""
    return strip_prefix(transcript, learn_prefixes)


def build_rewrite_system_prompt(instruction: str) -> str:
    """System prompt for the 'Edit:'/'Rewrite:' voice command.

    The user speaks an instruction (e.g. "make this more formal") while
    some text they want edited is sitting on their clipboard. The model
    receives the clipboard text as the user message and must return only
    the rewritten result.
    """
    return (
        "You are VoiceFlow's rewrite engine. The user has copied a piece of text "
        "to their clipboard and spoken an instruction for how to change it. You "
        "will receive that clipboard text as the message. Apply the instruction "
        "below to it and output ONLY the rewritten text - no commentary, no "
        "preamble, no quotation marks, no explanation of what you changed.\n\n"
        f'Instruction: "{instruction.strip()}"\n\n'
        "If the instruction is ambiguous, make the most reasonable interpretation "
        "rather than asking for clarification (you cannot ask - this is a "
        "one-shot batch rewrite). Preserve the original formatting (line breaks, "
        "lists, code blocks) unless the instruction asks you to change it."
    )


MEETING_SEGMENT_SYSTEM_PROMPT = """You are VoiceFlow's meeting-notes cleanup engine. You \
receive one raw, unpunctuated speech-to-text segment from an ongoing meeting or lecture \
recording. Clean it up for note-taking: remove filler words ("um", "uh", "like"), false \
starts, and self-corrections; add punctuation and capitalization; but do NOT summarize, \
shorten, paraphrase away specifics, or omit any content - this is a verbatim cleanup \
pass, not a summary. Output ONLY the cleaned segment text, nothing else. If the segment \
is empty, silence, or contains no discernible speech, output nothing at all.
"""

MEETING_SUMMARY_SYSTEM_PROMPT = """You are VoiceFlow's meeting-summary engine. You receive \
a full cleaned transcript of a meeting or lecture. Produce a concise Markdown summary with \
these sections, in this order:

## Summary
A short paragraph (2-4 sentences) capturing what the meeting/lecture was about.

## Key Points
A bullet list of the most important points, decisions, or facts discussed.

## Action Items
A bullet list of concrete follow-up actions or tasks mentioned (write "None mentioned" if \
there aren't any - do not invent action items that weren't discussed).

Output ONLY this Markdown, nothing before or after it.
"""


def parse_json_object(text: str) -> dict:
    """Robustly parse a JSON object out of an LLM response.

    Handles the common case of the model wrapping valid JSON in a markdown
    code fence, or prefixing it with stray whitespace/text, by falling back
    to extracting the first ``{...}`` block if a direct parse fails.
    """
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_BLOCK_RE.search(text)
        if match:
            return json.loads(match.group(0))
        raise
