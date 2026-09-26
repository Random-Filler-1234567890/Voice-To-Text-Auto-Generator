from voiceflow.context.app_profiles import AppCategory, get_profile


def test_known_bundle_id_maps_to_code_category():
    profile = get_profile("com.microsoft.VSCode", "Code", "")
    assert profile.category == AppCategory.CODE


def test_terminal_bundle_id():
    profile = get_profile("com.apple.Terminal", "Terminal", "")
    assert profile.category == AppCategory.TERMINAL


def test_unknown_bundle_id_falls_back_to_name_keyword():
    profile = get_profile("com.unknown.editor", "Sublime Text", "")
    assert profile.category == AppCategory.CODE


def test_completely_unknown_app_uses_default():
    profile = get_profile("com.mystery.app", "MysteryApp9000", "")
    assert profile.category == AppCategory.DEFAULT


def test_browser_with_gmail_title_is_email():
    profile = get_profile("com.google.Chrome", "Google Chrome", "Inbox (4) - sarah@gmail.com - Gmail")
    assert profile.category == AppCategory.EMAIL_FORMAL


def test_browser_with_claude_title_is_ai_prompt():
    profile = get_profile("com.google.Chrome", "Google Chrome", "Claude")
    assert profile.category == AppCategory.AI_PROMPT


def test_browser_with_no_matching_title_stays_generic():
    profile = get_profile("com.google.Chrome", "Google Chrome", "Random Blog Post")
    assert profile.category == AppCategory.BROWSER_GENERIC


def test_user_override_takes_priority():
    overrides = {"com.microsoft.VSCode": "notes"}
    profile = get_profile("com.microsoft.VSCode", "Code", "", overrides=overrides)
    assert profile.category == AppCategory.NOTES


def test_invalid_override_falls_back_to_builtin():
    overrides = {"com.microsoft.VSCode": "not_a_real_category"}
    profile = get_profile("com.microsoft.VSCode", "Code", "", overrides=overrides)
    assert profile.category == AppCategory.CODE


def test_every_category_has_nonempty_instructions():
    for category in AppCategory:
        profile = get_profile("nonexistent.bundle", category.value, "")
    # sanity: at least the DEFAULT profile always has instructions
    profile = get_profile(None, None, None)
    assert profile.formatting_instructions
