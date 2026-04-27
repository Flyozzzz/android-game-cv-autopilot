from core.cv_prompt_templates import INSTALL_GOAL_TEMPLATE, render_prompt_template


def test_render_prompt_template_replaces_known_placeholders():
    text = render_prompt_template(
        INSTALL_GOAL_TEMPLATE,
        {
            "game_name": "Example Game",
            "install_query": "Example",
            "profile_hints": "Skip optional login.",
            "operator_instructions": "Stop on errors.",
        },
    )

    assert "Example Game" in text
    assert "Skip optional login." in text
    assert "{game_name}" not in text


def test_render_prompt_template_keeps_unknown_placeholders_editable():
    text = render_prompt_template("Use {game_name} and {future_field}", {"game_name": "Game"})

    assert text == "Use Game and {future_field}"


def test_render_prompt_template_returns_raw_template_on_invalid_format():
    text = render_prompt_template("broken {", {"game_name": "Game"})

    assert text == "broken {"
