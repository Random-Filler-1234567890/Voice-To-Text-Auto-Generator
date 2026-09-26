import json

import pytest

from voiceflow.ai.prompts import (
    MEETING_SEGMENT_SYSTEM_PROMPT,
    MEETING_SUMMARY_SYSTEM_PROMPT,
    build_formatting_system_prompt,
    build_rewrite_system_prompt,
    parse_json_object,
    strip_learn_prefix,
    strip_prefix,
)
from voiceflow.context.app_profiles import get_profile

LEARN_PREFIXES = ["learn:", "remember:"]
EDIT_PREFIXES = ["edit:", "rewrite:"]


@pytest.mark.parametrize(
    "transcript,expected_remainder",
    [
        ("Learn: my boss is Sarah", "my boss is Sarah"),
        ("learn: my boss is Sarah", "my boss is Sarah"),
        ("LEARN: MY BOSS IS SARAH", "MY BOSS IS SARAH"),
        ("Remember: I like flat whites", "I like flat whites"),
        ("Learn my boss is Sarah", "my boss is Sarah"),  # whisper drops the colon sometimes
    ],
)
def test_strip_learn_prefix_detects_and_strips(transcript, expected_remainder):
    is_learn, remainder = strip_learn_prefix(transcript, LEARN_PREFIXES)
    assert is_learn is True
    assert remainder == expected_remainder


def test_strip_learn_prefix_ignores_normal_dictation():
    is_learn, remainder = strip_learn_prefix("please email the team about the launch", LEARN_PREFIXES)
    assert is_learn is False
    assert remainder == "please email the team about the launch"


def test_strip_learn_prefix_does_not_false_positive_on_substring():
    # "Learning" should not trigger the "Learn:" command.
    is_learn, _ = strip_learn_prefix("Learning how to cook is fun", LEARN_PREFIXES)
    assert is_learn is False


def test_parse_json_object_plain():
    result = parse_json_object('{"facts": []}')
    assert result == {"facts": []}


def test_parse_json_object_with_markdown_fence():
    text = '```json\n{"facts": [{"category": "fact", "text": "x"}]}\n```'
    result = parse_json_object(text)
    assert result["facts"][0]["text"] == "x"


def test_parse_json_object_with_surrounding_prose():
    text = 'Sure, here you go:\n{"facts": [{"category": "fact", "text": "x"}]}\nHope that helps!'
    result = parse_json_object(text)
    assert result["facts"][0]["text"] == "x"


def test_parse_json_object_invalid_raises():
    with pytest.raises(json.JSONDecodeError):
        parse_json_object("not json at all")


def test_formatting_prompt_includes_app_context_and_memory():
    profile = get_profile("com.apple.Terminal", "Terminal", "")
    prompt = build_formatting_system_prompt(
        profile, memory_snippets=["Sarah Chen is my boss"], remove_filler_words=True
    )
    assert "Terminal" in prompt
    assert "Sarah Chen is my boss" in prompt
    assert profile.formatting_instructions in prompt


def test_formatting_prompt_omits_memory_section_when_empty():
    profile = get_profile(None, None, None)
    prompt = build_formatting_system_prompt(profile, memory_snippets=[])
    assert "taught you the following facts" not in prompt


@pytest.mark.parametrize(
    "transcript,expected_remainder",
    [
        ("Edit: make this more formal", "make this more formal"),
        ("edit: make this more formal", "make this more formal"),
        ("Rewrite: shorten this", "shorten this"),
        ("Edit make this more formal", "make this more formal"),
    ],
)
def test_strip_prefix_detects_edit_commands(transcript, expected_remainder):
    is_edit, remainder = strip_prefix(transcript, EDIT_PREFIXES)
    assert is_edit is True
    assert remainder == expected_remainder


def test_strip_prefix_ignores_unrelated_text():
    is_edit, remainder = strip_prefix("please send this email", EDIT_PREFIXES)
    assert is_edit is False
    assert remainder == "please send this email"


def test_strip_prefix_bare_prefix_with_no_instruction():
    is_edit, remainder = strip_prefix("Edit:", EDIT_PREFIXES)
    assert is_edit is True
    assert remainder == ""


def test_build_rewrite_system_prompt_includes_instruction():
    prompt = build_rewrite_system_prompt("make this more formal")
    assert "make this more formal" in prompt
    assert "output" in prompt.lower()


def test_meeting_prompts_are_nonempty_and_distinct():
    assert MEETING_SEGMENT_SYSTEM_PROMPT.strip()
    assert MEETING_SUMMARY_SYSTEM_PROMPT.strip()
    assert MEETING_SEGMENT_SYSTEM_PROMPT != MEETING_SUMMARY_SYSTEM_PROMPT
    assert "not a summary" in MEETING_SEGMENT_SYSTEM_PROMPT.lower()
    assert "Action Items" in MEETING_SUMMARY_SYSTEM_PROMPT
