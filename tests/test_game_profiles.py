from core.game_profiles import (
    env_lines_for_profile,
    format_profiles_for_cli,
    game_profile_from_mapping,
    load_custom_game_profiles,
    list_game_profiles,
    resolve_game_profile,
)


def test_resolves_builtin_profile_by_alias():
    profile = resolve_game_profile("tom")

    assert profile.id == "talking-tom"
    assert profile.name == "My Talking Tom"
    assert profile.package == "com.outfit7.mytalkingtomfree"
    assert profile.proven is True
    assert profile.validation_status == "proven"
    assert "tutorial" in profile.validation_scope


def test_resolves_builtin_profile_by_package():
    profile = resolve_game_profile("com.king.candycrushsaga")

    assert profile.id == "candy-crush"
    assert profile.gameplay_strategy == "match3_solver"
    assert profile.screen_zones["match3_board"] == (0.07, 0.30, 0.93, 0.78)


def test_custom_profile_requires_package_for_reliable_runs():
    profile = resolve_game_profile("Some Game", package="com.example.game")

    assert profile.id == "custom"
    assert profile.name == "Some Game"
    assert profile.package == "com.example.game"


def test_cli_profile_format_lists_key_games():
    output = format_profiles_for_cli()

    assert "talking-tom" in output
    assert "brawl-stars" in output
    assert "subway-surfers" in output


def test_env_lines_for_profile():
    profile = resolve_game_profile("talking-tom")

    lines = env_lines_for_profile(profile)

    assert "GAME_PROFILE=talking-tom" in lines
    assert "GAME_PACKAGE=com.outfit7.mytalkingtomfree" in lines


def test_custom_profiles_are_loaded_from_dashboard_directory(monkeypatch, tmp_path):
    profile_path = tmp_path / "space-puzzle.json"
    profile_path.write_text(
        """
{
  "id": "space-puzzle",
  "name": "Space Puzzle",
  "package": "com.example.spacepuzzle",
  "aliases": ["space"],
  "tutorial_hints": ["skip account"],
  "purchase_hints": ["open shop"],
  "blocker_words": ["maintenance"],
  "gameplay_strategy": "match3_solver",
  "proven": true,
  "validation_status": "validated",
  "validation_scope": ["replay", "live"],
  "validation_runs": 2,
  "last_validated": "2026-04-28",
  "max_tutorial_steps": 44,
  "max_purchase_steps": 12,
  "screen_zones": {
    "board": [0.1, 0.2, 0.9, 0.8],
    "bad": [0.9, 0.2, 0.1, 0.8]
  }
}
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("GAME_PROFILE_DIR", str(tmp_path))

    profiles = {profile.id: profile for profile in list_game_profiles()}
    profile = resolve_game_profile("space")

    assert profiles["space-puzzle"].package == "com.example.spacepuzzle"
    assert profile.id == "space-puzzle"
    assert profile.gameplay_strategy == "match3_solver"
    assert profile.validation_status == "proven"
    assert profile.validation_runs == 2
    assert profile.last_validated == "2026-04-28"
    assert profile.max_purchase_steps == 12
    assert profile.screen_zones == {"board": (0.1, 0.2, 0.9, 0.8)}


def test_profile_mapping_defaults_and_invalid_values_are_normalized(tmp_path):
    profile = game_profile_from_mapping({
        "name": "Odd Game",
        "aliases": "odd, puzzle\ncasual",
        "tutorialHints": "tap start",
        "purchaseHints": 123,
        "blockerWords": None,
        "gameplayStrategy": "unknown",
        "maxTutorialSteps": "bad",
        "screenZones": {
            "": [0.1, 0.2, 0.3, 0.4],
            "short": [0.1, 0.2, 0.3],
            "not-a-box": "0.1,0.2,0.3,0.4",
            "bad-number": [0.1, "x", 0.3, 0.4],
            "outside": [-0.1, 0.2, 0.3, 0.4],
        },
    })
    scalar_profile = game_profile_from_mapping({"id": "Scalar", "aliases": 7})

    (tmp_path / "bad.json").write_text("{", encoding="utf-8")

    assert profile.id == "odd-game"
    assert profile.aliases == ("odd", "puzzle", "casual")
    assert profile.purchase_hints == ("123",)
    assert profile.blocker_words == ()
    assert profile.gameplay_strategy == "none"
    assert profile.max_tutorial_steps == 0
    assert scalar_profile.aliases == ("7",)
    assert load_custom_game_profiles(tmp_path) == ()
    assert load_custom_game_profiles(tmp_path / "missing") == ()


def test_builtin_profile_overrides_name_and_package():
    profile = resolve_game_profile(
        "talking-tom",
        game_name="Talking Tom QA",
        package="com.example.override",
    )

    assert profile.id == "talking-tom"
    assert profile.name == "Talking Tom QA"
    assert profile.package == "com.example.override"
