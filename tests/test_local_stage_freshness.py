import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config
from scenarios.google_register import GoogleRegisterScenario


WRONG_GMAIL_SETUP_XML = """
<hierarchy rotation="0">
  <node text="" class="android.widget.FrameLayout" package="com.google.android.gm" hint="" bounds="[0,0][1080,2400]">
    <node text="Add your email address" class="android.widget.TextView" package="com.google.android.gm" hint="" bounds="[63,336][1017,574]" />
    <node text="" class="android.widget.EditText" package="com.google.android.gm" hint="Enter your email" focused="true" bounds="[63,693][1017,845]" />
    <node text="Manual setup" class="android.widget.Button" package="com.google.android.gm" hint="" bounds="[21,1359][327,1485]" />
    <node text="Next" class="android.widget.Button" package="com.google.android.gm" hint="" bounds="[796,1359][1027,1485]" />
  </node>
</hierarchy>
"""

WRONG_GMS_EMAIL_SETUP_XML = WRONG_GMAIL_SETUP_XML.replace("com.google.android.gm", "com.google.android.gms")

NAME_FORM_WITH_KEYBOARD_XML = """
<hierarchy rotation="0">
  <node text="Create a Google Account" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,336][1017,430]" />
  <node text="Enter your name" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,430][1017,520]" />
  <node text="" class="android.widget.EditText" package="com.google.android.gms" hint="First name" focused="true" bounds="[63,568][1017,714]" />
  <node text="" class="android.widget.EditText" package="com.google.android.gms" hint="Last name (optional)" bounds="[63,778][1017,924]" />
  <node text="Next" class="android.widget.Button" package="com.google.android.gms" bounds="[806,1374][1017,1470]" />
</hierarchy>
"""

GMAIL_USERNAME_WITH_KEYBOARD_XML = """
<hierarchy rotation="0">
  <node text="How you'll sign in" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,336][1017,430]" />
  <node text="Create a Gmail address for signing in to your Google Account" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,430][1017,560]" />
  <node text="" class="android.widget.EditText" package="com.google.android.gms" hint="Username" focused="true" bounds="[63,630][1017,777]" />
  <node text="Next" class="android.widget.Button" package="com.google.android.gms" bounds="[806,1374][1017,1470]" />
</hierarchy>
"""


class FakeAction:
    def __init__(self, xml=WRONG_GMAIL_SETUP_XML, package="com.google.android.gm"):
        self.xml = xml
        self.package = package
        self.typed = []
        self.taps = []
        self.swipes = []
        self.keyevents = []
        self.pressed_enter = False

    async def _run_adb(self, *args, timeout=None):
        if args[:3] == ("shell", "uiautomator", "dump"):
            return "UI hierarchy dumped"
        if args[:2] == ("shell", "cat"):
            return self.xml
        if args[:3] == ("shell", "input", "tap"):
            self.taps.append((int(args[3]), int(args[4])))
            return ""
        if args[:3] == ("shell", "input", "swipe"):
            self.swipes.append(tuple(map(int, args[3:7])))
            return ""
        if args[:3] == ("shell", "input", "keyevent"):
            self.keyevents.append(args[3:])
            return ""
        return ""

    async def get_current_package(self):
        return self.package

    async def get_current_activity(self):
        return ""

    async def force_portrait(self):
        return None

    async def _mshell(self, *args, timeout=None):
        return ""

    async def tap_by_text(self, *args, **kwargs):
        return False

    async def tap_by_text_scroll(self, *args, **kwargs):
        return False

    async def tap_by_text_contains_scroll(self, *args, **kwargs):
        return False

    async def scroll_to_text_contains(self, *args, **kwargs):
        return False

    async def get_visible_texts(self):
        return []

    async def swipe_up(self):
        return None

    async def clear_field(self):
        return None

    async def type_text(self, text, pause=0):
        self.typed.append(text)

    async def press_enter(self):
        self.pressed_enter = True

    async def open_app(self, package):
        self.package = package


class LocalGmsSignInAction(FakeAction):
    async def open_app(self, package):
        # Simulate Play Store immediately routing into the GMS sign-in WebView.
        self.package = "com.google.android.gms"


class RaisingPackageAction(FakeAction):
    async def get_current_package(self):
        raise RuntimeError("package lookup unavailable")


class DumpFailsWithStaleCatAction(FakeAction):
    async def _run_adb(self, *args, timeout=None):
        if args[:3] == ("shell", "uiautomator", "dump"):
            return ""
        if args[:2] == ("shell", "cat"):
            raise AssertionError("failed dumps must not read stale /sdcard/uidump.xml")
        return await super()._run_adb(*args, timeout=timeout)


class PlayStoreNoDumpScenario(GoogleRegisterScenario):
    async def find_and_tap(self, *args, **kwargs):
        return False

    async def tap_text(self, *args, **kwargs):
        return False

    async def _tap_create_account_and_for_myself(self, action):
        return None


class PlayStoreStaleSignInTapScenario(PlayStoreNoDumpScenario):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.find_calls = 0

    async def find_and_tap(self, *args, **kwargs):
        self.find_calls += 1
        # Simulates the latest live failure: text lookup reports success from a
        # stale/wrong bound tap, but the package remains Play Store landing.
        if self.find_calls == 1:
            return True
        return False


class PlayStoreLandsInSettingsAccountPickerScenario(PlayStoreNoDumpScenario):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.navigated_settings = False

    async def find_and_tap(self, *args, **kwargs):
        self.action.package = "com.android.settings"
        return True

    async def _navigate_settings_to_google_create(self):
        self.navigated_settings = True


class SettingsBlankAccountPickerScenario(GoogleRegisterScenario):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.create_account_called = False

    async def get_texts(self):
        # Simulates local settings account picker when ADB/UI text extraction is flaky:
        # the screen is visible, but dumps/text helpers return no rows.
        return []

    async def find_and_tap(self, *args, **kwargs):
        return False

    async def _tap_create_account_and_for_myself(self, action):
        self.create_account_called = True


class StaleBirthdayScenario(GoogleRegisterScenario):
    async def get_texts(self):
        # Simulates the previous failure mode: stale page-source/text cache still
        # says birthday after the UI has already moved to Gmail setup.
        return [("Basic information Enter your birthday and gender Month Day Year Gender", 10, 10)]

    async def tap_text(self, *args, **kwargs):
        return False

    async def tap_text_contains(self, *args, **kwargs):
        return False

    async def type_into_field(self, *args, **kwargs):
        return False


class EmptyDumpStaleEmailScenario(StaleBirthdayScenario):
    async def get_texts(self):
        # If local ADB XML is empty/failed, stale Appium text must not drive
        # the local flow into the email stage and blind-type into the focused app.
        return [("Add your email address Enter your email", 10, 10)]


def test_local_stage_detection_prefers_fresh_adb_xml_over_stale_birthday_text(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    scenario = StaleBirthdayScenario(None, FakeAction(), sms_service=None)

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "wrong_email_setup"


def test_local_play_store_gms_create_account_uses_current_no_keyboard_coordinate(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    action = LocalGmsSignInAction(package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)

    opened = asyncio.run(scenario._open_signup_via_play_store())

    assert opened is True
    assert (197, 1176) in action.taps
    assert (197, 2050) not in action.taps
    assert any(tap in action.taps for tap in [(240, 1235), (278, 1308)])


def test_local_play_store_gms_create_account_recovers_keyboard_visible_sign_in(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    action = LocalGmsSignInAction(package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)

    opened = asyncio.run(scenario._open_signup_via_play_store())

    assert opened is True
    assert action.taps.index((197, 1176)) < action.taps.index((197, 1222))
    assert action.taps.index((197, 1222)) < action.taps.index((315, 1356))
    assert (197, 2050) not in action.taps


def test_local_stage_detection_treats_gms_add_email_as_wrong_route(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    scenario = StaleBirthdayScenario(
        None,
        FakeAction(xml=WRONG_GMS_EMAIL_SETUP_XML, package="com.google.android.gms"),
        sms_service=None,
    )

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "wrong_email_setup"


def test_local_birthday_does_not_type_or_press_next_when_current_xml_lacks_birthday_controls(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction()
    scenario = StaleBirthdayScenario(None, action, sms_service=None)
    scenario.credentials = {
        "birth_month": "1",
        "birth_day": "17",
        "birth_year": "2006",
        "gender": "male",
    }

    ok = asyncio.run(scenario._do_fill_birthday())

    assert ok is False
    assert action.typed == []
    assert action.pressed_enter is False


def test_local_empty_adb_xml_does_not_fallback_to_stale_email_stage(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    scenario = EmptyDumpStaleEmailScenario(None, FakeAction(xml=""), sms_service=None)

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "unknown"


def test_local_failed_adb_dump_does_not_read_stale_remote_xml(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    scenario = GoogleRegisterScenario(
        None,
        DumpFailsWithStaleCatAction(xml=WRONG_GMS_EMAIL_SETUP_XML, package="com.google.android.gms"),
        sms_service=None,
    )

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "unknown"


def test_local_name_submit_taps_keyboard_visible_next_not_hidden_bottom_next(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml=NAME_FORM_WITH_KEYBOARD_XML, package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario.credentials.update({"first_name": "Joshua", "last_name": "Gonzalez"})

    ok = asyncio.run(scenario._do_fill_name())

    assert ok is True
    assert action.typed == ["Joshua", "Gonzalez"]
    assert (911, 1422) in action.taps
    assert (911, 2242) not in action.taps


def test_local_name_expectation_survives_empty_package_when_xml_is_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_name_after_gms_create = True

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "name"


def test_local_name_expectation_survives_package_lookup_failure_when_xml_is_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = RaisingPackageAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_name_after_gms_create = True

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "name"


def test_local_birthday_expectation_survives_empty_xml_after_name(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_birthday_after_name = True

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "birthday"


def test_local_birthday_coordinate_fallback_when_expected_and_xml_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_birthday_after_name = True
    scenario.credentials = {
        "birth_month": "6",
        "birth_day": "17",
        "birth_year": "2006",
        "gender": "male",
    }

    ok = asyncio.run(scenario._do_fill_birthday())

    assert ok is True
    assert "17" in action.typed
    assert "2006" in action.typed
    assert (215, 641) in action.taps
    assert (215, 1428) in action.taps
    assert (540, 830) in action.taps
    assert (540, 1113) in action.taps
    assert action.pressed_enter is True
    assert (912, 2208) in action.taps
    assert (912, 2020) not in action.taps


def test_local_birthday_success_marks_email_stage_when_next_xml_is_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_birthday_after_name = True
    scenario.credentials = {
        "birth_month": "6",
        "birth_day": "17",
        "birth_year": "2006",
        "gender": "male",
    }

    ok = asyncio.run(scenario._do_fill_birthday())
    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert ok is True
    assert stage == "email"


def test_local_email_stage_uses_guarded_coordinate_entry_when_expected_after_birthday_and_xml_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario._local_expect_email_after_birthday = True
    scenario.credentials = {
        "email_username": "amy.lewis4478",
        "first_name": "Amy",
        "last_name": "Lewis",
    }

    ok = asyncio.run(scenario._do_fill_email())

    assert ok is True
    assert action.taps[0] == (540, 703)
    assert ("123",) in action.keyevents
    assert len([keys for keys in action.keyevents if keys == ("67",)]) >= 80
    assert action.typed == ["amylewis4478"]
    assert (912, 1422) in action.taps
    assert scenario._local_expect_email_after_birthday is False


def test_local_email_success_marks_password_stage_when_next_xml_is_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario._local_expect_email_after_birthday = True
    scenario.credentials = {
        "email_username": "amy.lewis4478",
        "first_name": "Amy",
        "last_name": "Lewis",
    }

    ok = asyncio.run(scenario._do_fill_email())
    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert ok is True
    assert stage == "password"


def test_local_password_stage_uses_guarded_coordinate_entry_when_expected_after_email_and_xml_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario._local_expect_password_after_email = True
    scenario.credentials = {"password": "SafePass123!"}

    ok = asyncio.run(scenario._do_fill_password())

    assert ok is True
    assert action.taps[0] == (540, 703)
    assert ("123",) in action.keyevents
    assert len([keys for keys in action.keyevents if keys == ("67",)]) >= 80
    assert action.typed == ["SafePass123!"]
    assert (912, 1422) in action.taps
    assert scenario._local_expect_password_after_email is True


def test_local_password_submit_keeps_guard_until_next_stage_is_observed(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario._local_expect_password_after_email = True
    scenario.credentials = {"password": "***"}

    ok = asyncio.run(scenario._do_fill_password())
    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert ok is True
    assert scenario._local_expect_password_after_email is True
    assert stage == "password"


class SignInIdentifierVisibleTextAction(FakeAction):
    async def get_visible_texts(self):
        return [("Sign in Email or phone Enter an email or phone number Create account Next", 63, 336)]


def test_local_password_guard_does_not_override_visible_sign_in_identifier_route(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = SignInIdentifierVisibleTextAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_password_after_email = True

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "signin_create"


def test_local_password_guard_reopens_create_account_after_repeated_empty_xml_submits(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_password_after_email = True
    scenario._local_password_empty_xml_submit_attempts = 2

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "signin_create"


def test_local_birthday_coordinate_fallback_supports_december_with_dropdown_scroll(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_birthday_after_name = True
    scenario.credentials = {
        "birth_month": "12",
        "birth_day": "17",
        "birth_year": "2006",
        "gender": "female",
    }

    ok = asyncio.run(scenario._do_fill_birthday())

    assert ok is True
    assert action.swipes, "December is below the visible month menu and must scroll before tapping"
    assert "17" in action.typed
    assert "2006" in action.typed
    assert action.pressed_enter is True
    assert (540, 986) in action.taps
    assert (912, 2208) in action.taps
    assert (912, 2020) not in action.taps


def test_local_name_expectation_does_not_override_settings_package(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.android.settings")
    scenario = GoogleRegisterScenario(None, action, sms_service=None)
    scenario._local_expect_name_after_gms_create = True

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "settings"


def test_local_play_store_sign_in_uses_coordinate_fallback_when_ui_dump_is_flaky(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.android.vending")
    scenario = PlayStoreNoDumpScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())

    assert ok is False
    assert (540, 1580) in action.taps


def test_local_play_store_sign_in_retries_coordinate_fallback_when_stale_text_tap_leaves_landing(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.android.vending")
    scenario = PlayStoreStaleSignInTapScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())

    assert ok is False
    assert (540, 1580) in action.taps


class PlayStoreSignInTapRoutesToSettingsAction(FakeAction):
    async def _run_adb(self, *args, timeout=None):
        result = await super()._run_adb(*args, timeout=timeout)
        if args[:5] == ("shell", "input", "tap", "540", "1580"):
            self.package = "com.android.settings"
        return result


def test_local_play_store_sign_in_hands_off_to_settings_account_picker(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = PlayStoreSignInTapRoutesToSettingsAction(xml="", package="com.android.vending")
    scenario = PlayStoreLandsInSettingsAccountPickerScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())

    assert ok is True
    assert scenario.navigated_settings is True


class PlayStoreSignInTapRoutesToGmsAction(FakeAction):
    async def _run_adb(self, *args, timeout=None):
        result = await super()._run_adb(*args, timeout=timeout)
        if args[:5] == ("shell", "input", "tap", "540", "1580"):
            self.package = "com.google.android.gms"
        return result


class GmsCreateAccountNoDumpScenario(PlayStoreNoDumpScenario):
    async def find_and_tap(self, *args, **kwargs):
        raise AssertionError("local GMS sign-in should tap Create account coordinates before flaky UI dump lookup")

    async def tap_text(self, *args, **kwargs):
        return False


def test_local_gms_sign_in_taps_create_account_coordinates_before_flaky_lookup(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = PlayStoreSignInTapRoutesToGmsAction(xml="", package="com.android.vending")
    scenario = GmsCreateAccountNoDumpScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())

    assert ok is True
    assert (197, 1176) in action.taps
    assert (197, 2050) not in action.taps
    assert any(tap in action.taps for tap in [(240, 1235), (278, 1308)])


def test_local_gms_create_account_coordinate_path_marks_name_stage_when_xml_is_empty(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = PlayStoreSignInTapRoutesToGmsAction(xml="", package="com.android.vending")
    scenario = GmsCreateAccountNoDumpScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())
    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert ok is True
    assert stage == "name"


class SelectPersonalUseScenario(GoogleRegisterScenario):
    async def tap_text(self, label, *args, **kwargs):
        return label in {"Create account", "For my personal use"}

    async def find_and_tap(self, *args, **kwargs):
        raise AssertionError("text tap should select personal-use option in this regression")


def test_local_generic_create_account_helper_marks_name_stage_after_personal_use(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.google.android.gms")
    scenario = SelectPersonalUseScenario(None, action, sms_service=None)

    asyncio.run(scenario._tap_create_account_and_for_myself(action))
    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "name"


def test_local_settings_account_picker_uses_google_coordinate_fallback_when_text_dump_is_flaky(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.android.settings")
    scenario = SettingsBlankAccountPickerScenario(None, action, sms_service=None)

    asyncio.run(scenario._navigate_settings_to_google_create())

    assert (285, 500) in action.taps
    assert scenario.create_account_called is True


def test_local_email_stage_refuses_blind_typing_without_fresh_signup_xml(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario.credentials = {"email_username": "safeuser"}

    ok = asyncio.run(scenario._do_fill_email())

    assert ok is False
    assert action.typed == []
    assert action.taps == []


def test_local_email_stage_hard_clears_existing_username_and_uses_safe_ascii_username(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml=GMAIL_USERNAME_WITH_KEYBOARD_XML, package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario.credentials = {
        "email_username": "amy.lewis4478",
        "first_name": "Amy",
        "last_name": "Lewis",
    }

    ok = asyncio.run(scenario._do_fill_email())

    assert ok is True
    assert action.taps[0] == (540, 703)
    assert ("123",) in action.keyevents  # KEYCODE_MOVE_END before repeated DEL
    assert len([keys for keys in action.keyevents if keys == ("67",)]) >= 80
    assert action.typed == ["amylewis4478"]
    assert (911, 1422) in action.taps


class GmailEmptyAddressErrorAction(FakeAction):
    async def get_visible_texts(self):
        return [("How you'll sign in Username Enter a Gmail address Next", 63, 336)]


def test_local_email_stage_treats_enter_gmail_address_as_retryable_empty_field_error(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = GmailEmptyAddressErrorAction(xml=GMAIL_USERNAME_WITH_KEYBOARD_XML, package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario.credentials = {
        "email_username": "amy.lewis4478",
        "first_name": "Amy",
        "last_name": "Lewis",
    }

    ok = asyncio.run(scenario._do_fill_email())

    assert ok is False
    assert len(action.typed) == 5
    assert all(text.isascii() and text.isalnum() for text in action.typed)
    assert action.typed[0] == "amylewis4478"

GMAIL_SUGGESTIONS_XML = """
<hierarchy rotation="0">
  <node text="Create an email address" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,336][1017,430]" />
  <node text="Create a Gmail address for signing in to your Google Account" class="android.widget.TextView" package="com.google.android.gms" bounds="[63,430][1017,560]" />
  <node text="[REDACTED_EMAIL]" class="android.widget.TextView" package="com.google.android.gms" checked="true" bounds="[160,650][900,720]" />
  <node text="[REDACTED_EMAIL]" class="android.widget.TextView" package="com.google.android.gms" checked="false" bounds="[160,820][900,890]" />
  <node text="Create your own Gmail address" class="android.widget.TextView" package="com.google.android.gms" checked="false" bounds="[160,1000][900,1070]" />
  <node text="Next" class="android.widget.Button" package="com.google.android.gms" bounds="[806,2000][1017,2096]" />
</hierarchy>
"""

def test_local_email_stage_accepts_selected_google_suggestion_when_no_username_field(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml=GMAIL_SUGGESTIONS_XML, package="com.google.android.gms")
    scenario = EmptyDumpStaleEmailScenario(None, action, sms_service=None)
    scenario.credentials = {
        "email_username": "amylewis4478",
        "first_name": "Amy",
        "last_name": "Lewis",
    }

    ok = asyncio.run(scenario._do_fill_email())

    assert ok is True
    assert action.typed == []
    assert (911, 2048) in action.taps
    assert scenario._local_expect_password_after_email is True


GMS_ERROR_XML = """
<hierarchy rotation="0">
  <node text="" class="android.widget.FrameLayout" package="com.google.android.gms" hint="" bounds="[0,0][1080,2400]">
    <node text="Something went wrong" class="android.widget.TextView" package="com.google.android.gms" hint="" bounds="[63,701][1017,780]" />
    <node text="Please go back and try again." class="android.widget.TextView" package="com.google.android.gms" hint="" bounds="[63,825][1017,900]" />
  </node>
</hierarchy>
"""


class StrictNoAppiumTextAction(FakeAction):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.opened_settings = False

    async def get_visible_texts(self):
        raise AssertionError("local open path must not call Appium get_visible_texts")

    async def open_settings(self, section=None):
        self.opened_settings = True
        self.package = "com.android.settings"


class OpenSignupSafeLocalScenario(PlayStoreNoDumpScenario):
    async def _open_signup_via_play_store(self) -> bool:
        return False

    async def _navigate_settings_to_google_create(self):
        return None


def test_local_stage_detection_classifies_gms_error_activity_for_recovery(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    scenario = StaleBirthdayScenario(
        None,
        FakeAction(xml=GMS_ERROR_XML, package="com.google.android.gms"),
        sms_service=None,
    )

    stage = asyncio.run(scenario._detect_stage_from_page_source())

    assert stage == "gms_error"


def test_local_open_google_signup_does_not_call_appium_visible_texts(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = StrictNoAppiumTextAction(xml=GMS_ERROR_XML, package="com.google.android.gms")
    scenario = OpenSignupSafeLocalScenario(None, action, sms_service=None)

    asyncio.run(scenario._open_google_signup())

    assert action.opened_settings is True


class PlayStoreDirectCoordinateScenario(PlayStoreNoDumpScenario):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.find_calls = 0

    async def find_and_tap(self, *args, **kwargs):
        self.find_calls += 1
        raise AssertionError("local Play Store landing should use coordinate Sign in before flaky UI dump lookup")


def test_local_play_store_sign_in_taps_coordinate_before_flaky_ui_dump_lookup(monkeypatch):
    monkeypatch.setattr(config, "DEVICE_FARM", "local")
    action = FakeAction(xml="", package="com.android.vending")
    scenario = PlayStoreDirectCoordinateScenario(None, action, sms_service=None)

    ok = asyncio.run(scenario._open_signup_via_play_store())

    assert ok is False
    assert scenario.find_calls == 0
    assert action.taps and action.taps[0] == (540, 1580)
