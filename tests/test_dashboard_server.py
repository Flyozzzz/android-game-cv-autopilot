import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dashboard.server import (
    DashboardHandler,
    _default_settings,
    _preset_files,
    _project_files,
    _resolve_project_file,
    _resolve_recording_path,
    _settings_to_env,
)


def test_dashboard_env_forces_purchase_preview():
    env = _settings_to_env(
        {
            "stages": ["install", "purchase_preview"],
            "purchaseMode": "preview",
            "googlePhoneMode": "manual",
            "gameProfile": "talking-tom",
            "gamePackage": "com.outfit7.mytalkingtomfree",
        }
    )

    assert env["PURCHASE_MODE"] == "preview"
    assert env["GOOGLE_PHONE_MODE"] == "manual"
    assert env["GAME_PROFILE"] == "talking-tom"


def test_dashboard_blocks_real_purchase_mode():
    try:
        _settings_to_env({"purchaseMode": "real"})
    except RuntimeError as exc:
        assert "preview" in str(exc)
    else:
        raise AssertionError("real purchase mode should be blocked")


def test_dashboard_blocks_non_manual_google_phone_mode():
    try:
        _settings_to_env({"googlePhoneMode": "fivesim"})
    except RuntimeError as exc:
        assert "manual" in str(exc)
    else:
        raise AssertionError("non-manual Google phone mode should be blocked")


def test_dashboard_gameplay_off_removes_gameplay_stage():
    env = _settings_to_env(
        {
            "stages": ["install", "tutorial", "gameplay", "purchase_preview"],
            "gameplayMethod": "off",
        }
    )

    assert env["RUN_STAGES"] == "install,tutorial,purchase_preview"


def test_dashboard_passes_cv_key_only_when_supplied():
    env = _settings_to_env({"openrouterKey": "test-openrouter-token-value"})

    assert env["OPENROUTER_API_KEY"] == "test-openrouter-token-value"


def test_dashboard_recorded_method_paths_are_exported():
    env = _settings_to_env(
        {
            "installMethod": "recorded",
            "tutorialMethod": "recorded",
            "gameplayMethod": "recorded",
            "recordedInstallPath": "dashboard/recordings/install.json",
            "recordedTutorialPath": "dashboard/recordings/tutorial.json",
            "recordedGameplayPath": "dashboard/recordings/gameplay.json",
        }
    )

    assert env["INSTALL_AUTOPILOT_VIA"] == "recorded"
    assert env["RECORDED_TUTORIAL_PATH"] == "dashboard/recordings/tutorial.json"
    assert env["RECORDED_GAMEPLAY_PATH"] == "dashboard/recordings/gameplay.json"


def test_dashboard_base_prompts_are_exported():
    env = _settings_to_env(
        {
            "cvInstallBasePrompt": "Install {game_name}",
            "cvTutorialBasePrompt": "Tutorial {profile_hints}",
            "cvPurchaseBasePrompt": "Preview {operator_instructions}",
        }
    )

    assert env["CV_INSTALL_GOAL_TEMPLATE"] == "Install {game_name}"
    assert env["CV_TUTORIAL_GOAL_TEMPLATE"] == "Tutorial {profile_hints}"
    assert env["CV_PURCHASE_GOAL_TEMPLATE"] == "Preview {operator_instructions}"


def test_dashboard_default_base_prompts_are_editable_templates():
    settings = _default_settings()

    assert "{game_name}" in settings["cvInstallBasePrompt"]
    assert "{profile_hints}" in settings["cvTutorialBasePrompt"]
    assert "{operator_instructions}" in settings["cvPurchaseBasePrompt"]


def test_dashboard_ready_presets_are_available():
    names = {preset["name"] for preset in _preset_files()}

    assert "01_talking_tom_verified" in names
    assert "05_full_manual_template" in names


def test_dashboard_can_save_delete_custom_profile(monkeypatch, tmp_path):
    import dashboard.server as server

    monkeypatch.setenv("GAME_PROFILE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PROFILES_DIR", tmp_path)
    handler = object.__new__(DashboardHandler)

    saved = handler._save_profile({
        "profile": {
            "id": "new-game",
            "name": "New Game",
            "package": "com.example.newgame",
            "aliases": ["ng"],
            "tutorial_hints": ["skip sign in"],
            "purchase_hints": ["open store"],
            "blocker_words": ["server"],
            "gameplay_strategy": "none",
            "max_tutorial_steps": "33",
            "max_purchase_steps": "11",
        }
    })
    profiles = handler._profiles_payload()
    profile = next(item for item in profiles if item["id"] == "new-game")

    assert saved["path"].endswith("new-game.json")
    assert profile["source"] == "custom"
    assert profile["maturity"] == "starter"
    assert profile["production_ready"] is False
    assert profile["settings"]["gamePackage"] == "com.example.newgame"
    assert profile["settings"]["cvTutorialInstructions"] == "skip sign in"
    assert handler._delete_profile({"id": "new-game"})["deleted"] is True
    assert not (tmp_path / "new-game.json").exists()


def test_dashboard_can_save_delete_named_preset(monkeypatch, tmp_path):
    import dashboard.server as server

    monkeypatch.setattr(server, "PRESETS_DIR", tmp_path)
    monkeypatch.setattr(server, "LATEST_PRESET", tmp_path / "latest.json")
    handler = object.__new__(DashboardHandler)

    saved = handler._save_named_preset({
        "name": "new_route",
        "title": "New Route",
        "description": "constructor preset",
        "settings": {
            "gameName": "New Game",
            "gamePackage": "com.example.newgame",
            "purchaseMode": "preview",
            "googlePhoneMode": "manual",
            "openrouterKey": "secret-value-should-not-save",
        },
    })
    content = (tmp_path / "new_route.json").read_text()

    assert saved["path"].endswith("new_route.json")
    assert "secret-value-should-not-save" not in content
    assert "New Route" in content
    assert handler._delete_preset({"path": saved["path"]})["deleted"] is True
    with pytest.raises(RuntimeError, match="latest"):
        handler._delete_preset({"path": str(tmp_path / "latest.json")})


def test_project_file_guard_allows_safe_dashboard_data_file():
    path, rel = _resolve_project_file("dashboard/presets/01_talking_tom_verified.json")

    assert path.exists()
    assert rel == "dashboard/presets/01_talking_tom_verified.json"


def test_project_file_guard_blocks_outside_paths():
    with pytest.raises(RuntimeError):
        _resolve_project_file("../.zshrc")


def test_project_file_guard_blocks_server_code():
    for path in ("config.py", "dashboard/server.py", "dashboard/static/app.js", "main.py"):
        with pytest.raises(RuntimeError):
            _resolve_project_file(path)


def test_project_files_only_include_safe_dashboard_data():
    paths = {item["path"] for item in _project_files()}

    assert "dashboard/presets/01_talking_tom_verified.json" in paths
    assert "dashboard/recordings/tutorial_path.json" in paths
    assert "dashboard/server.py" not in paths
    assert "dashboard/static/app.js" not in paths
    assert "config.py" not in paths
    assert not any(path.startswith("legacy/") for path in paths)


def test_recording_path_guard_blocks_outside_paths():
    with pytest.raises(RuntimeError):
        _resolve_recording_path("../config.py")
