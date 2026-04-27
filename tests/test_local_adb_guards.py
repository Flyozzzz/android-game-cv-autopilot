import asyncio
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scenarios.base import BaseScenario


class _FailingDumpAction:
    async def _run_adb(self, *args, timeout=None):
        if args[:3] == ("shell", "uiautomator", "dump"):
            raise RuntimeError("dump failed")
        if args[:2] == ("shell", "cat"):
            return '<node text="Next" bounds="[850,1370][972,1474]" />'
        raise AssertionError(f"unexpected adb call: {args}")


class _NonThrowingFailingDumpAction:
    async def _run_adb(self, *args, timeout=None):
        if args[:3] == ("shell", "uiautomator", "dump"):
            return "ERROR: could not get idle state."
        if args[:2] == ("shell", "cat"):
            return '<node text="Next" bounds="[850,1370][972,1474]" />'
        raise AssertionError(f"unexpected adb call: {args}")


class _DummyScenario(BaseScenario):
    NAME = "dummy"

    async def run(self):
        return True


def test_name_stage_no_stale_low_coordinate_next_tap():
    src = (ROOT / "scenarios" / "google_register.py").read_text()
    assert "int(h * 0.40)" not in src
    assert "int(h * 0.47)" not in src
    assert "int(h * 0.59)" not in src
    assert "Filled name via local ADB EditText path" in src


def test_find_and_type_local_skips_appium_driver_and_uses_adb_even_with_driver():
    src = (ROOT / "scenarios" / "base.py").read_text()
    assert "hasattr(self.action, 'driver') and getattr(config, \"DEVICE_FARM\", \"local\") != \"local\"" in src
    assert "if not found and not hasattr(self.action, 'driver')" not in src
    assert "await self.action.tap_by_text_contains(kw, pause=0.5)" not in src
    assert "await self.tap_text_contains(kw, pause=0.5)" in src


def test_base_adb_dump_does_not_read_stale_xml_after_dump_failure():
    scenario = _DummyScenario(None, _FailingDumpAction())

    xml = asyncio.run(scenario._dump_ui_xml_adb())

    assert xml == ""


def test_base_adb_dump_does_not_read_stale_xml_after_non_throwing_dump_failure():
    scenario = _DummyScenario(None, _NonThrowingFailingDumpAction())

    xml = asyncio.run(scenario._dump_ui_xml_adb())

    assert xml == ""


def test_local_farm_check_api_uses_configured_appium_port_and_stable_adb_path():
    src = (ROOT / "services" / "local_farm.py").read_text()

    assert "appium_url = f\"http://localhost:{config.APPIUM_PORT}\"" in src
    assert "client.get(f\"{appium_url}/status\")" in src
    assert "shutil.which(\"adb\")" in src
    assert "options.udid = self.device_serial" in src
    assert "Multiple Android devices are connected" in src
    assert "uiautomator2ServerInstallTimeout" in src
    assert "adbExecTimeout" in src


def test_genymotion_custom_recipe_can_fallback_to_other_recipes():
    src = (ROOT / "main.py").read_text()
    cfg = (ROOT / "config.py").read_text()

    assert "GENYMOTION_RECIPE_ALLOW_FALLBACK" in cfg
    assert "allow_recipe_fallback" in src
    assert "seen_recipe_ids" in src


def test_local_logs_do_not_call_local_device_browserstack():
    main_src = (ROOT / "main.py").read_text()
    engine_src = (ROOT / "core" / "appium_action_engine.py").read_text()

    assert "Local Android" in main_src
    assert "Appium session active ({farm})" in engine_src


def test_purchase_stage_requires_card_or_explicit_override():
    main_src = (ROOT / "main.py").read_text()
    cfg = (ROOT / "config.py").read_text()

    assert "ALLOW_PURCHASE_WITHOUT_CARD" in cfg
    assert "ALLOW_PURCHASE_WITHOUT_CARD=0" in main_src
    assert "PURCHASE_MODE" in cfg
    assert "PurchasePreviewCVScenario" in main_src


def test_game_and_purchase_have_cv_safe_modes():
    main_src = (ROOT / "main.py").read_text()
    install_src = (ROOT / "scenarios" / "install_game_cv.py").read_text()
    tutorial_src = (ROOT / "scenarios" / "game_tutorial_cv.py").read_text()
    preview_src = (ROOT / "scenarios" / "purchase_preview_cv.py").read_text()
    prompt_src = (ROOT / "core" / "cv_prompt_templates.py").read_text()
    cfg = (ROOT / "config.py").read_text()
    profiles_src = (ROOT / "core" / "game_profiles.py").read_text()

    assert "CV_COORDINATE_SCALE" in cfg
    assert "GAME_PROFILE" in cfg
    assert "SELECTED_GAME_PROFILE" in cfg
    assert "GAME_NAME" in cfg
    assert "GAME_PACKAGE" in cfg
    assert "com.supercell.brawlstars" in profiles_src
    assert "com.outfit7.mytalkingtomfree" in profiles_src
    assert "com.king.candycrushsaga" in profiles_src
    assert "GAME_APK_PATH" in cfg
    assert "InstallGameCVScenario" in main_src
    assert "FastRunnerGameplayScenario" in main_src
    assert "Match3GameplayScenario" in main_src
    assert "RunReport" in main_src
    assert "CVAutopilot" in install_src
    assert "self.game_name" in install_src
    assert "self.package_name" in install_src
    assert "self.profile.install_query" in install_src
    assert "unavailable in this Play Store country" in install_src
    assert "_install_from_apk" in install_src
    assert "GameTutorialCVScenario" in main_src
    assert "CVAutopilot" in tutorial_src
    assert "self.profile.tutorial_hints" in tutorial_src
    assert "safe first-run onboarding" in prompt_src
    assert "CVAutopilot" in preview_src
    assert "self.profile.purchase_hints" in preview_src
    assert "Do not tap Buy" in prompt_src
    assert "visible price buttons" in prompt_src
    assert "Purchase Preview" in preview_src


def test_google_registration_has_cv_autopilot_mode():
    main_src = (ROOT / "main.py").read_text()
    cfg = (ROOT / "config.py").read_text()
    scenario_src = (ROOT / "scenarios" / "google_register_cv.py").read_text()

    assert '"cv"' in cfg
    assert "GoogleRegisterCVScenario" in main_src
    assert "CVAutopilot" in scenario_src
    assert "OPENROUTER_API_KEY" in scenario_src
    assert "signup_url" in scenario_src
    assert "--activity-clear-task" in scenario_src
    assert "CV autopilot" in main_src


def test_google_login_waits_for_webview_inputs_and_has_local_adb_edittext_fallback():
    src = (ROOT / "scenarios" / "google_login.py").read_text()

    assert "async def _wait_for_edittext" in src
    assert "async def _wait_for_password_input" in src
    assert "await self._wait_for_edittext(\"email\", timeout=60)" in src
    assert "await self._wait_for_password_input(timeout=45)" in src
    assert "async def _tap_first_edittext_from_adb" in src
    assert "Email entered (ADB EditText)" in src
    assert "Password entered (ADB EditText)" in src
    assert "Refusing to type password into email error screen" in src
