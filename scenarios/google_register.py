"""
Сценарий: Регистрация НОВОГО Google-аккаунта на Android.

БЕЗ CV — всё через UIAutomator2 page_source + deterministic actions.

Flow:
  Play Store → Sign in → Create Account → For Myself
  → (deterministic) Имя → Дата рождения → Email → Пароль
  → (SMS inject) Телефон → Код подтверждения
  → (deterministic) Terms → Extra screens → Done
"""
from __future__ import annotations

import asyncio
import random
import re
from loguru import logger

import config
from core.credentials import CredentialsGenerator, MONTHS
from scenarios.base import BaseScenario
from scenarios.phone_checkpoint import PhoneVerificationReached
from services.manual_verification import ManualVerification
from services.sms_service import SMSService


# Стадии, которые сигнализируют об успешном завершении
_DONE_SCREENS = frozenset({
    "home_screen", "google_account_done",
    "play_store_app_page", "play_store_installed",
})

# Сколько одинаковых подряд провальных шагов считать «зависанием»
_STALL_THRESHOLD = 3


class GoogleRegisterScenario(BaseScenario):

    NAME = "google_register"

    def __init__(self, cv, action, sms_service: SMSService):
        super().__init__(cv, action)
        self.sms = sms_service
        self.creds_gen = CredentialsGenerator()
        self.credentials: dict = {}
        self.phone_data: dict = {}
        self._local_expect_name_after_gms_create = False
        self._local_expect_birthday_after_name = False
        self._local_expect_email_after_birthday = False
        self._local_expect_password_after_email = False
        self._local_password_empty_xml_submit_attempts = 0

    # ─────────────────────────────────────────────────────────────
    # Точка входа
    # ─────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        logger.info("=" * 60)
        logger.info("  SCENARIO: Register NEW Google Account (UIAutomator2)")
        logger.info("=" * 60)

        # Генерация учётных данных
        self.credentials = self.creds_gen.generate()
        logger.info(f"  Name:     {self.credentials['first_name']} {self.credentials['last_name']}")
        logger.info(f"  Email:    {self.credentials['full_email']}")
        logger.info(f"  Birthday: {self.credentials['birth_year']}-"
                    f"{self.credentials['birth_month']}-{self.credentials['birth_day']}")

        # Готовим легальный источник телефона/кода. По умолчанию manual:
        # пользователь задаёт свой реальный номер через GOOGLE_PHONE_NUMBER,
        # а код — через GOOGLE_SMS_CODE или GOOGLE_SMS_CODE_FILE.
        self.phone_data = await self._prepare_phone_data()
        logger.success(f"Phone source: {self.phone_data.get('operator', '?')} / {self.phone_data['phone']}")

        try:
            # Открываем форму регистрации через Play Store (или Settings-fallback)
            await self._open_google_signup()

            # Deterministic автопилот (без CV, без LLM)
            success = await self._run_deterministic_autopilot(max_steps=80)
            if not success:
                raise RuntimeError("Deterministic autopilot did not complete registration")

            logger.success("=" * 60)
            logger.success("  ✅ Google Account REGISTERED!")
            logger.success(f"  Email:    {self.credentials['full_email']}")
            logger.success(f"  Password: {self.credentials['password']}")
            logger.success("=" * 60)

            config.GOOGLE_EMAIL = self.credentials["full_email"]
            config.GOOGLE_PASSWORD = self.credentials["password"]
            return self.credentials

        except Exception as e:
            logger.error(f"Registration failed: {e}")
            if self.phone_data and self.phone_data.get("id") not in ("manual", "manual_checkpoint"):
                try:
                    await self.sms.cancel_order(self.phone_data["id"])
                except Exception:
                    pass
            raise

    async def _prepare_phone_data(self) -> dict:
        """Return phone data for registration.

        Legal default is manual/user-owned phone. Legacy 5sim auto-buy is only
        enabled when GOOGLE_PHONE_MODE=fivesim is explicitly set.
        """
        mode = getattr(config, "GOOGLE_PHONE_MODE", "manual").strip().lower()
        if mode != "fivesim":
            if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
                self._log_step("Phone checkpoint mode enabled; no phone number required before signup")
                return {
                    "id": "manual_checkpoint",
                    "phone": "",
                    "operator": "manual_checkpoint",
                    "status": "CHECKPOINT",
                    "price": 0,
                }
            self._log_step("Using manual legal phone verification (GOOGLE_PHONE_NUMBER)")
            return ManualVerification(input_func=None).phone_data()

        self._log_step("Buying phone number for verification (GOOGLE_PHONE_MODE=fivesim)...")
        try:
            return await self.sms.buy_number_with_retry(
                service="google",
                countries=["indonesia"],
                operators=["virtual53", "virtual4", "virtual58", "any"],
            )
        except Exception as e:
            raise RuntimeError(f"SMS number required for Google registration: {e}")

    def _is_manual_phone(self) -> bool:
        return (self.phone_data or {}).get("id") == "manual"

    async def _wait_for_manual_sms_code(self, timeout: int = 600) -> str:
        self._log_step(
            "Waiting for manual SMS code. Set GOOGLE_SMS_CODE or write it to GOOGLE_SMS_CODE_FILE."
        )
        return await ManualVerification(input_func=None).wait_for_code(
            timeout=timeout,
            poll_interval=3.0,
        )

    # ─────────────────────────────────────────────────────────────
    # Deterministic автопилот (БЕЗ CV, БЕЗ LLM)
    # ─────────────────────────────────────────────────────────────

    async def _run_deterministic_autopilot(self, max_steps: int = 80) -> bool:
        """
        Цикл: определить стадию через page_source → deterministic действие → повтор.
        Специальные случаи:
          - phone_input: вводим номер → ждём SMS-код
          - phone_code:  вводим полученный код
        """
        sms_code: str | None = None
        phone_entered = False
        stall_counter = 0
        last_stage = ""

        for step in range(1, max_steps + 1):
            await asyncio.sleep(0.8)

            # Определяем стадию через UIAutomator2 page_source
            stage = await self._detect_stage_from_page_source()

            self._log_step(f"Step {step}/{max_steps} | stage={stage}")

            # Проверяем завершение
            if stage == "done":
                self._log_step(f"Done detected at step {step}")
                return True

            # Антизависание
            if stage == last_stage:
                stall_counter += 1
            else:
                stall_counter = 0
                last_stage = stage

            if stall_counter >= _STALL_THRESHOLD:
                await self._handle_stall(stage, step)
                stall_counter = 0
                continue

            # ── Sign-in start screen: choose account creation again ──
            if stage == "signin_create":
                await self._tap_create_account_and_for_myself(self.action)
                await asyncio.sleep(2)
                continue

            # ── Стадия: ввод имени ──
            if stage == "name":
                ok = await self._do_fill_name()
                if ok:
                    await asyncio.sleep(2)
                continue

            # ── Стадия: день рождения ──
            if stage == "birthday":
                ok = await self._do_fill_birthday()
                if ok:
                    await asyncio.sleep(2)
                continue

            # ── Стадия: email ──
            if stage == "email":
                ok = await self._do_fill_email()
                if ok:
                    await asyncio.sleep(2)
                continue

            # ── Стадия: пароль ──
            if stage == "password":
                ok = await self._do_fill_password()
                if ok:
                    await asyncio.sleep(2)
                continue

            # ── Стадия: ввод номера телефона ──
            if stage == "phone_input" and not phone_entered:
                if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
                    self._log_step("Phone verification screen reached; stopping before phone entry as requested")
                    raise PhoneVerificationReached(stage="phone_input")
                ok = await self._do_enter_phone()
                if ok:
                    phone_entered = True
                    self._log_step("Phone entered, waiting for SMS...")
                    sms_code = await self._wait_for_sms_with_retry()
                    self._log_step(f"SMS code: {'received' if sms_code else 'FAILED'}")
                continue

            # ── Стадия: ввод SMS-кода ──
            if stage == "phone_code":
                if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
                    self._log_step("Phone code screen reached; stopping before SMS verification as requested")
                    raise PhoneVerificationReached(stage="phone_code")
                if sms_code:
                    ok = await self._do_enter_code(sms_code)
                    self._log_step(f"Code entered: {'ok' if ok else 'fail'}")
                else:
                    self._log_step("Waiting for SMS code (not yet received)...")
                    await asyncio.sleep(5)
                continue

            # ── Стадия: Terms ──
            if stage == "terms":
                await self._do_accept_terms()
                await asyncio.sleep(2)
                continue

            # ── Стадия: дополнительные экраны ──
            if stage == "extras":
                await self._do_skip_extras()
                await asyncio.sleep(2)
                continue

            # ── Стадия: Settings навигация ──
            if stage == "settings":
                await self._navigate_settings_to_google_create()
                await asyncio.sleep(2)
                continue

            # ── Wrong Android/Gmail email setup route ──
            if stage == "wrong_email_setup":
                self._log_step("Wrong Gmail/Android email setup screen detected; reopening Google signup")
                await self._open_signup_via_settings_fallback()
                await asyncio.sleep(2)
                continue

            # ── Recoverable GMS add-account error ──
            if stage == "gms_error":
                self._log_step("GMS add-account ErrorActivity detected; reopening Google signup")
                await self._open_signup_via_settings_fallback()
                await asyncio.sleep(2)
                continue

            # ── Неизвестная стадия ──
            if stage == "unknown":
                # Пробуем стандартные dismiss/next действия
                await self._try_common_actions()
                continue

        logger.warning(f"Autopilot exhausted {max_steps} steps without 'done'")
        return False

    # ─────────────────────────────────────────────────────────────
    # Deterministic действия для каждой стадии
    # ─────────────────────────────────────────────────────────────

    async def _do_fill_name(self) -> bool:
        """Заполнить First Name и Last Name."""
        vals = self._signup_values()
        first = vals["first_name"]
        last = vals["last_name"]

        # Local emulator path: prefer real EditText bounds from ADB UI XML.
        # Previous hardcoded coordinates were too low for the GMS WebView name
        # page (actual fields are around y=640/850 on 1080x2400), so typing did
        # not focus inputs and the flow looped forever on stage=name.
        if getattr(config, "DEVICE_FARM", "local") == "local":
            self._local_expect_name_after_gms_create = False
            first_ok = await self._type_in_nth_edittext(0, first)
            last_ok = await self._type_in_nth_edittext(1, last)
            if not (first_ok and last_ok):
                # Last-resort coordinates for the observed API 36 GMS WebView.
                w = getattr(config, "SCREEN_WIDTH", 1080) or 1080
                h = getattr(config, "SCREEN_HEIGHT", 2400) or 2400
                first_x, first_y = int(w * 0.50), int(h * 0.267)  # ~540,640
                last_x, last_y = int(w * 0.50), int(h * 0.354)    # ~540,850
                await self.action.tap(first_x, first_y, pause=0.2)
                await self.action.clear_field()
                await self.action.type_text(first, pause=0.2)
                await self.action.tap(last_x, last_y, pause=0.2)
                await self.action.clear_field()
                await self.action.type_text(last, pause=0.2)
            await self._press_local_keyboard_visible_next()
            self._local_expect_birthday_after_name = True
            self._log_step("Filled name via local ADB EditText path")
            return True

        # Ищем поля по hint/label
        filled_first = await self.type_into_field("First name", first)
        if not filled_first:
            filled_first = await self.type_into_field("first name", first)
        if not filled_first:
            # Fallback: первый EditText
            await self._type_in_nth_edittext(0, first)

        await asyncio.sleep(0.3)

        filled_last = await self.type_into_field("Last name", last)
        if not filled_last:
            filled_last = await self.type_into_field("last name", last)
        if not filled_last:
            # Fallback: второй EditText
            await self._type_in_nth_edittext(1, last)

        await asyncio.sleep(0.5)
        await self._press_next()
        return True

    async def _do_fill_birthday(self) -> bool:
        """Заполнить день рождения и пол."""
        vals = self._signup_values()
        month = str(int(vals["birth_month"]))
        day = str(vals["birth_day"])
        year = str(vals["birth_year"])
        gender = vals.get("gender", "").lower()

        if getattr(config, "DEVICE_FARM", "local") == "local":
            # Local GMS WebView exposes birthday fields in ADB XML as:
            # - android.widget.Spinner hint="Month Please fill in a complete birthday"
            # - android.widget.EditText hint="Day Please fill in a complete birthday"
            # - android.widget.EditText hint="Year Please fill in a complete birthday"
            # - android.widget.Spinner hint="Gender"
            # Text-label taps miss these because Month/Gender are hints, not text.
            if not await self._local_xml_has_birthday_controls():
                if self._local_expect_birthday_after_name:
                    ok = await self._local_fill_birthday_by_guarded_coordinates(month, day, year, gender)
                    self._local_expect_birthday_after_name = False
                    if ok:
                        self._local_expect_email_after_birthday = True
                    return ok
                self._log_step("Local birthday controls absent; refusing to type stale birthday data")
                return False
            self._local_expect_birthday_after_name = False
            month_name = MONTHS[int(month) - 1] if 1 <= int(month) <= 12 else ""
            if month_name:
                await self._tap_node_by_class_and_hint("android.widget.Spinner", "Month Please fill in a complete birthday")
                await asyncio.sleep(0.5)
                await self.tap_text(month_name, pause=0.5)
            await self._type_edittext_by_hint("Day Please fill in a complete birthday", day)
            await self._type_edittext_by_hint("Year Please fill in a complete birthday", year)
            gender_val = "Male" if ("male" in gender and "fe" not in gender) else "Female"
            await self._tap_node_by_class_and_hint("android.widget.Spinner", hint_prefix="Gender")
            await asyncio.sleep(0.5)
            if not await self.tap_text(gender_val, pause=0.5):
                await self.tap_text("Rather not say", pause=0.5)
            await asyncio.sleep(0.5)
            await self._press_next()
            self._local_expect_email_after_birthday = True
            self._log_step("Local birthday via ADB Spinner/EditText bounds path")
            return True

        # Месяц — dropdown/spinner
        month_filled = False
        # Пробуем tap по месяцу
        month_name = MONTHS[int(month) - 1] if 1 <= int(month) <= 12 else ""
        if month_name:
            month_filled = await self.tap_text_contains(month_name, pause=0.5)
        if not month_filled:
            # Пробуем tap на Month label → выбрать из списка
            await self.tap_text_contains("Month", pause=0.5)
            await asyncio.sleep(0.5)
            if month_name:
                await self.tap_text(month_name, pause=0.5)
            else:
                await self.tap_text(str(int(month)), pause=0.5)

        await asyncio.sleep(0.3)

        # День
        day_filled = await self.type_into_field("Day", day)
        if not day_filled:
            day_filled = await self.type_into_field("day", day)
        if not day_filled:
            await self._type_in_nth_edittext(0, day)

        await asyncio.sleep(0.3)

        # Год
        year_filled = await self.type_into_field("Year", year)
        if not year_filled:
            year_filled = await self.type_into_field("year", year)
        if not year_filled:
            await self._type_in_nth_edittext(1, year)

        await asyncio.sleep(0.3)

        # Пол — dropdown
        gender_val = "Male" if ("male" in gender and "fe" not in gender) else "Female"
        await self.tap_text_contains("Gender", pause=0.5)
        await asyncio.sleep(0.5)
        await self.tap_text(gender_val, pause=0.5)
        # Fallback: "Rather not say"
        if not await self.is_text_visible(gender_val):
            await self.tap_text("Rather not say", pause=0.5)

        await asyncio.sleep(0.5)
        await self._press_next()
        return True

    async def _do_fill_email(self) -> bool:
        """Заполнить username для Gmail."""
        if getattr(config, "DEVICE_FARM", "local") == "local":
            xml = await self._dump_adb_xml()
            local_guarded_expected_email = False
            if not self._local_xml_allows_gmail_username_entry(xml):
                pkg = ""
                try:
                    pkg = (await self.action.get_current_package() or "").lower()
                except Exception:
                    pass
                local_guarded_expected_email = (
                    self._local_expect_email_after_birthday
                    and "settings" not in pkg
                    and "android.vending" not in pkg
                )
                if not local_guarded_expected_email:
                    self._log_step("Local email stage guard: fresh XML is not Gmail username signup; refusing blind typing")
                    return False
                self._log_step("Local post-birthday email guard: XML empty/unavailable, using focused Gmail username coordinate")
        else:
            local_guarded_expected_email = False

        if getattr(config, "DEVICE_FARM", "local") == "local" and self._local_xml_has_selected_gmail_suggestion(xml):
            self._log_step("Local Gmail suggestion screen detected; accepting selected suggested address")
            await self._press_local_keyboard_visible_next()
            self._local_expect_email_after_birthday = False
            self._local_password_empty_xml_submit_attempts = 0
            self._local_expect_password_after_email = True
            return True

        # Пробуем выбрать "Create your own Gmail address"
        await self.tap_text_contains("Create your own", pause=1.0)
        await asyncio.sleep(0.5)

        for attempt in range(5):
            username = self._safe_gmail_username(self.credentials.get("email_username", ""))
            if attempt > 0:
                # Генерируем новый уникальный username. Keep it strictly ASCII
                # alnum for ADB input/WebView reliability on the local emulator.
                suffix = "".join(random.choices("0123456789", k=4))
                base = self._safe_gmail_username(
                    f"{self.credentials.get('first_name','user')}{self.credentials.get('last_name','x')}"
                )
                username = f"{base}{suffix}"
                logger.info("Username taken — trying another generated username")

            self.credentials["email_username"] = username
            self.credentials["full_email"] = f"{username}@gmail.com"

            # Вводим username
            if getattr(config, "DEVICE_FARM", "local") == "local":
                if local_guarded_expected_email:
                    typed = await self._local_type_gmail_username_by_guarded_coordinate(username)
                else:
                    typed = await self._local_type_gmail_username(username)
            else:
                typed = await self.type_into_field("Create a Gmail address", username)
                if not typed:
                    typed = await self.type_into_field("Gmail address", username)
                if not typed:
                    typed = await self.type_into_field("username", username)
                if not typed:
                    # Fallback: первый EditText
                    await self._type_in_nth_edittext(0, username)
                    typed = True

            if not typed:
                return False

            await asyncio.sleep(0.5)
            if getattr(config, "DEVICE_FARM", "local") == "local":
                await self._press_local_keyboard_visible_next()
            else:
                await self._press_next()
            await asyncio.sleep(2)

            # Проверяем — нет ли ошибки "taken"
            if await self._check_username_error():
                logger.warning("Username unavailable, retrying...")
                # Очищаем поле для следующей попытки
                if getattr(config, "DEVICE_FARM", "local") == "local":
                    await self._local_hard_clear_focused_text()
                else:
                    await self.action.clear_field()
                continue

            self._local_expect_email_after_birthday = False
            self._local_password_empty_xml_submit_attempts = 0
            if getattr(config, "DEVICE_FARM", "local") == "local":
                self._local_expect_password_after_email = True
            return True  # успешно

        return False

    async def _do_fill_password(self) -> bool:
        """Заполнить пароль и подтверждение."""
        password = self.credentials.get("password", "")

        if getattr(config, "DEVICE_FARM", "local") == "local":
            xml = await self._dump_adb_xml()
            local_guarded_expected_password = False
            if not self._local_xml_allows_password_entry(xml):
                pkg = ""
                try:
                    pkg = (await self.action.get_current_package() or "").lower()
                except Exception:
                    pass
                local_guarded_expected_password = (
                    self._local_expect_password_after_email
                    and "settings" not in pkg
                    and "android.vending" not in pkg
                )
                if not local_guarded_expected_password:
                    self._log_step("Local password stage guard: fresh XML is not password signup; refusing blind typing")
                    return False
                self._log_step("Local post-email password guard: XML empty/unavailable, using focused password coordinate")

            if local_guarded_expected_password:
                typed = await self._local_type_password_by_guarded_coordinate(password)
            else:
                typed = await self._local_type_password_from_xml(password)
            if not typed:
                return False
            await asyncio.sleep(0.5)
            await self._press_local_keyboard_visible_next()
            if local_guarded_expected_password:
                self._local_password_empty_xml_submit_attempts += 1
            # Keep the post-email password guard active until a later stage is
            # actually observed. On Android 16/GMS the first keyboard-visible
            # Next tap can leave the user on the password page with empty XML;
            # clearing the guard here turns that retry into an unsafe unknown.
            return True

        # Пробуем поля пароля
        pwd_filled = await self.type_into_field("Create a password", password)
        if not pwd_filled:
            pwd_filled = await self.type_into_field("Password", password)
        if not pwd_filled:
            pwd_filled = await self.type_into_field("password", password)
        if not pwd_filled:
            await self._type_in_nth_edittext(0, password)

        await asyncio.sleep(0.5)

        # Подтверждение пароля
        confirm_filled = await self.type_into_field("Confirm", password)
        if not confirm_filled:
            confirm_filled = await self.type_into_field("confirm", password)
        if not confirm_filled:
            # Fallback: второй EditText (или Tab к следующему)
            await self.action.press_tab()
            await asyncio.sleep(0.3)
            await self.action.clear_field()
            await self.action.type_text(password)

        await asyncio.sleep(0.5)
        await self._press_next()
        return True

    async def _do_enter_phone(self) -> bool:
        """Ввести номер телефона через UIAutomator2."""
        phone_clean = self.phone_data["phone"].lstrip("+")

        # Пробуем найти поле по label
        typed = await self.type_into_field("phone number", phone_clean)
        if not typed:
            typed = await self.type_into_field("Phone", phone_clean)
        if not typed:
            typed = await self.type_into_field("phone", phone_clean)
        if not typed:
            # Fallback: первый EditText
            await self._type_in_nth_edittext(0, phone_clean)

        await asyncio.sleep(0.5)
        await self._press_next()
        return True

    async def _do_enter_code(self, code: str) -> bool:
        """Ввести SMS-код через UIAutomator2."""
        # Пробуем найти поле по label
        typed = await self.type_into_field("verification code", code)
        if not typed:
            typed = await self.type_into_field("code", code)
        if not typed:
            typed = await self.type_into_field("Enter code", code)
        if not typed:
            # Fallback: первый EditText
            await self._type_in_nth_edittext(0, code)

        await asyncio.sleep(0.5)
        await self._press_next()
        return True

    async def _do_accept_terms(self) -> bool:
        """Принять Terms of Service."""
        # Скроллим вниз
        await self.action.swipe_up()
        await asyncio.sleep(1)

        # Пробуем кнопки
        for label in ["I agree", "I Agree", "Agree", "Accept", "Accept all"]:
            if await self.tap_text(label, pause=2.0):
                return True

        # Fallback: page_source поиск
        texts = await self.action.get_visible_texts()
        for text, cx, cy in texts:
            if any(kw in text.lower() for kw in ("agree", "accept", "confirm")):
                await self.action.tap(cx, cy, pause=2.0)
                return True

        # Пробуем Enter
        await self.action.press_enter()
        await asyncio.sleep(2)
        return True

    async def _do_skip_extras(self) -> bool:
        """Пропустить дополнительные экраны."""
        for label in ["Skip", "SKIP", "Not now", "NOT NOW", "Later", "No thanks",
                      "NO THANKS", "Maybe later", "Cancel", "CANCEL"]:
            if await self.tap_text(label, pause=1.5):
                self._log_step(f"Skipped extra: '{label}'")
                return True

        # Fallback: tap "Continue" или "Next"
        for label in ["Continue", "CONTINUE", "Next", "NEXT", "Done", "DONE"]:
            if await self.tap_text(label, pause=1.5):
                return True

        await self.action.press_back()
        await asyncio.sleep(1)
        return True

    async def _try_common_actions(self) -> bool:
        """Попробовать стандартные действия для неизвестных экранов."""
        # Dismiss popups
        if await self.handle_unexpected_popup():
            return True

        # Пробуем Next/Continue
        for label in ["Next", "Continue", "Done", "Accept", "I agree"]:
            if await self.tap_text(label, pause=1.5):
                return True

        # Swipe up как последнее средство
        await self.action.swipe_up()
        await asyncio.sleep(1)
        return False

    async def _handle_stall(self, stage: str, step: int):
        """Обработка зависания на одной стадии."""
        self._log_step(f"Stall detected on stage={stage} at step {step}")

        # Пробуем dismiss popups
        dismissed = False
        for label in ["No thanks", "Skip", "Not now", "Later", "Cancel"]:
            if await self.tap_text(label, pause=1.0):
                dismissed = True
                break

        if not dismissed:
            if getattr(config, "DEVICE_FARM", "local") == "local":
                # Do not press Back on local Google signup stalls: it returns from
                # the form to the sign-in landing page and restarts the flow.
                self._log_step("Local stall: skip Back to avoid leaving signup form")
                return
            # Пробуем Back
            await self.action.press_back()
            await asyncio.sleep(1)

    # ─────────────────────────────────────────────────────────────
    # Вспомогательные методы
    # ─────────────────────────────────────────────────────────────

    async def _local_hard_clear_focused_text(self, max_chars: int = 100):
        """Clear focused WebView text field using only ADB keyevents.

        CTRL+A is flaky in the Android 16 GMS WebView/Gboard combination. Move
        the caret to the end and backspace enough times to remove stale text from
        previous attempts before typing a new username.
        """
        await self.action._run_adb("shell", "input", "keyevent", "123", timeout=5)  # KEYCODE_MOVE_END
        await asyncio.sleep(0.05)
        for _ in range(max_chars):
            await self.action._run_adb("shell", "input", "keyevent", "67", timeout=5)  # KEYCODE_DEL
        await asyncio.sleep(0.1)

    @staticmethod
    def _safe_gmail_username(username: str) -> str:
        """Return a conservative ASCII Gmail username for local ADB typing."""
        safe = re.sub(r"[^a-z0-9]", "", (username or "").lower())
        if not safe or not safe[0].isalnum():
            safe = f"user{safe}"
        return safe[:28]

    async def _local_type_gmail_username(self, username: str) -> bool:
        """Tap the Gmail username EditText, hard-clear stale text, then type."""
        xml = await self._dump_adb_xml()
        for attrs in self._node_attrs(xml):
            if attrs.get("class") != "android.widget.EditText":
                continue
            label = (attrs.get("hint") or attrs.get("text") or attrs.get("content-desc") or "").lower()
            if "username" not in label and "gmail" not in label:
                continue
            center = self._bounds_center(attrs.get("bounds", ""))
            if not center:
                continue
            await self.action._run_adb("shell", "input", "tap", str(center[0]), str(center[1]), timeout=5)
            await asyncio.sleep(0.2)
            await self._local_hard_clear_focused_text()
            await self.action.type_text(username, pause=0.2)
            return True
        return False

    async def _local_type_gmail_username_by_guarded_coordinate(self, username: str) -> bool:
        """Post-birthday only fallback for focused local Gmail username screen.

        This is intentionally not a generic unknown-stage fallback: it is called
        only when the deterministic flow just submitted birthday successfully and
        fresh XML is empty/unavailable on the expected next GMS screen.
        """
        await self.action._run_adb("shell", "input", "tap", "540", "703", timeout=5)
        await asyncio.sleep(0.2)
        await self._local_hard_clear_focused_text()
        await self.action.type_text(username, pause=0.2)
        return True

    @staticmethod
    def _safe_local_password(password: str) -> str:
        """Return a password safe for local ADB input text.

        Generated project passwords are normally printable ASCII and work with
        the ActionEngine escaping. If tests or callers pass an unusable placeholder
        such as *** / empty, replace it with a deterministic strong password and
        keep credentials in sync before continuing the signup flow.
        """
        password = str(password or "")
        if len(password) < 8 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password):
            return "SafePass123!"
        return password

    def _local_xml_allows_password_entry(self, xml: str) -> bool:
        """True only for the Google signup password creation page."""
        if not xml:
            return False
        labels = " ".join(
            (node.get("text") or node.get("hint") or node.get("content-desc") or "").lower()
            for node in self._node_attrs(xml)
        )
        return any(
            marker in labels
            for marker in (
                "create a strong password",
                "create password",
                "create a password",
                "confirm password",
                "strong password",
            )
        )

    async def _local_type_password_from_xml(self, password: str) -> bool:
        """Tap password EditText from fresh XML, hard-clear stale text, then type."""
        safe_password = self._safe_local_password(password)
        if safe_password != password:
            self.credentials["password"] = safe_password
        xml = await self._dump_adb_xml()
        for attrs in self._node_attrs(xml):
            if attrs.get("class") != "android.widget.EditText":
                continue
            label = (attrs.get("hint") or attrs.get("text") or attrs.get("content-desc") or "").lower()
            if "password" not in label:
                continue
            center = self._bounds_center(attrs.get("bounds", ""))
            if not center:
                continue
            await self.action._run_adb("shell", "input", "tap", str(center[0]), str(center[1]), timeout=5)
            await asyncio.sleep(0.2)
            await self._local_hard_clear_focused_text()
            await self.action.type_text(safe_password, pause=0.2)
            return True
        return False

    async def _local_type_password_by_guarded_coordinate(self, password: str) -> bool:
        """Post-email only fallback for focused local password screen.

        This is intentionally not a generic unknown-stage fallback: it is called
        only when the deterministic flow just submitted Gmail username successfully
        and fresh XML is empty/unavailable on the expected next GMS screen.
        """
        safe_password = self._safe_local_password(password)
        if safe_password != password:
            self.credentials["password"] = safe_password
        await self.action._run_adb("shell", "input", "tap", "540", "703", timeout=5)
        await asyncio.sleep(0.2)
        await self._local_hard_clear_focused_text()
        await self.action.type_text(safe_password, pause=0.2)
        return True

    async def _local_fill_birthday_by_guarded_coordinates(self, month: str, day: str, year: str, gender: str) -> bool:
        """Guarded 1080x2400 local fallback for GMS birthday screen when XML is empty."""
        self._log_step("Local birthday XML empty after name; using guarded coordinate fallback")
        month_num = int(month)
        month_y_by_num = {
            1: 790,
            2: 920,
            3: 1050,
            4: 1175,
            5: 1300,
            6: 1428,
            7: 1555,
            8: 1680,
            9: 1805,
            10: 1932,
            11: 2058,
        }
        if month_num < 1 or month_num > 12:
            self._log_step("Guarded birthday fallback received invalid month; refusing blind typing")
            return False

        await self.action._run_adb("shell", "input", "tap", "215", "641", timeout=5)
        await asyncio.sleep(0.4)
        if month_num == 12:
            # December sits just below the visible dropdown on the observed
            # 1080x2400/2160 local GMS layout. A small upward swipe reveals one
            # more row, then the old November row position selects December.
            await self.action._run_adb("shell", "input", "swipe", "540", "2058", "540", "1932", timeout=5)
            await asyncio.sleep(0.3)
            await self.action._run_adb("shell", "input", "tap", "215", "2058", timeout=5)
        else:
            await self.action._run_adb("shell", "input", "tap", "215", str(month_y_by_num[month_num]), timeout=5)
        await asyncio.sleep(0.2)

        await self.action._run_adb("shell", "input", "tap", "540", "641", timeout=5)
        await self.action.clear_field()
        await self.action.type_text(day, pause=0.1)
        await asyncio.sleep(0.2)

        await self.action._run_adb("shell", "input", "tap", "865", "641", timeout=5)
        await self.action.clear_field()
        await self.action.type_text(year, pause=0.1)
        await asyncio.sleep(0.2)
        # On local GMS WebView the birthday Next button remains inert until the
        # Year field is committed/keyboard hidden. Press Enter before tapping
        # the bottom button; otherwise the autopilot loops forever on this page.
        await self.action.press_enter()
        await asyncio.sleep(0.5)

        await self.action._run_adb("shell", "input", "tap", "540", "830", timeout=5)
        await asyncio.sleep(0.4)
        gender_y = "1113" if ("male" in gender.lower() and "fe" not in gender.lower()) else "986"
        await self.action._run_adb("shell", "input", "tap", "540", gender_y, timeout=5)
        await asyncio.sleep(0.3)
        await self.action._run_adb("shell", "input", "tap", "912", "2208", timeout=5)
        await asyncio.sleep(1.0)
        return True

    async def _press_local_keyboard_visible_next(self):
        """Press the visible local GMS Next button when keyboard is open.

        The normal text tap can fall back to stale bottom-of-screen bounds
        (around y=2242). On the name page with the keyboard open, the real Next
        button is much higher (around y=1422), so use a fresh XML button bound
        when available and otherwise a guarded coordinate for the observed local
        1080x2400 WebView layout.
        """
        xml = await self._dump_adb_xml()
        for label, x, y in self._texts_from_adb_xml(xml):
            if label.strip().lower() == "next":
                await self.action._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                await asyncio.sleep(1.5)
                self._log_step("Pressed local keyboard-visible Next")
                return

        await self.action._run_adb("shell", "input", "tap", "912", "1422", timeout=5)
        await asyncio.sleep(1.5)
        self._log_step("Pressed guarded local keyboard-visible Next coordinate")

    async def _press_next(self):
        """Нажать Next/Continue/Далее."""
        for label in ["Next", "Continue", "Далее"]:
            if await self.tap_text(label, pause=1.5):
                self._log_step(f"Pressed '{label}'")
                return
        # Fallback: Enter
        await self.action.press_enter()
        await asyncio.sleep(1)

    async def _type_in_nth_edittext(self, n: int, value: str) -> bool:
        """Ввести текст в n-й EditText на экране. Engine-agnostic."""
        import re

        clicked = False

        # Путь 1: Appium driver. Skip on local: UiAutomator2 is unstable here.
        if hasattr(self.action, 'driver') and getattr(config, "DEVICE_FARM", "local") != "local":
            try:
                from appium.webdriver.common.appiumby import AppiumBy
                def _type():
                    els = self.action.driver.find_elements(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiSelector().className("android.widget.EditText")'
                    )
                    if n < len(els):
                        els[n].click()
                        return True
                    return False
                clicked = await self.action._run(_type, timeout=8)
            except Exception:
                pass

        # Путь 2: ADB uiautomator dump
        if not clicked:
            try:
                await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
                _xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
                bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
                edit_count = 0
                for node in re.finditer(r'<node\b[^>]*?/?>', _xml):
                    ns = node.group(0)
                    if 'class="android.widget.EditText"' not in ns:
                        continue
                    if edit_count == n:
                        m = bounds_re.search(ns)
                        if m:
                            x = (int(m.group(1)) + int(m.group(3))) // 2
                            y = (int(m.group(2)) + int(m.group(4))) // 2
                            await self.action._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                            clicked = True
                            break
                    edit_count += 1
            except Exception:
                pass

        if clicked:
            await asyncio.sleep(0.3)
            await self.action.clear_field()
            await self.action.type_text(value)
            return True
        return False

    async def _dump_adb_xml(self) -> str:
        """Return current Android UI XML via host ADB path.

        uiautomator can fail on local API 36 while leaving an old /sdcard/uidump.xml
        behind. Treat a failed/empty dump command as no XML instead of reading stale
        contents from a previous screen.
        """
        try:
            await self.action._run_adb("shell", "rm", "-f", "/sdcard/uidump.xml", timeout=5)
            dump_out = await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            if "dump" not in (dump_out or "").lower() and "uidump.xml" not in (dump_out or "").lower():
                return ""
            xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            return xml if "<hierarchy" in xml else ""
        except Exception:
            return ""

    def _node_attrs(self, xml: str):
        """Yield attribute dicts for uiautomator <node> elements."""
        import html
        import re
        for match in re.finditer(r'<node\b[^>]*?/?>', xml or ""):
            node = match.group(0)
            attrs = {k: html.unescape(v) for k, v in re.findall(r'(\w[\w-]*)="([^"]*)"', node)}
            yield attrs

    def _texts_from_adb_xml(self, xml: str):
        """Extract visible-ish text/hint/content-desc triples from ADB XML."""
        texts = []
        for attrs in self._node_attrs(xml):
            label = attrs.get("text") or attrs.get("hint") or attrs.get("content-desc") or ""
            label = label.strip()
            if not label:
                continue
            center = self._bounds_center(attrs.get("bounds", "")) or (0, 0)
            texts.append((label, center[0], center[1]))
        return texts

    async def _local_xml_has_birthday_controls(self) -> bool:
        """Return True only when the fresh local XML is actually the birthday form."""
        xml = await self._dump_adb_xml()
        attrs = list(self._node_attrs(xml))

        def has_node(class_name: str, hint_prefix: str) -> bool:
            for node in attrs:
                if node.get("class") != class_name:
                    continue
                label = node.get("hint") or node.get("text") or node.get("content-desc") or ""
                if label.startswith(hint_prefix):
                    return True
            return False

        return (
            has_node("android.widget.Spinner", "Month Please fill in a complete birthday")
            and has_node("android.widget.EditText", "Day Please fill in a complete birthday")
            and has_node("android.widget.EditText", "Year Please fill in a complete birthday")
            and has_node("android.widget.Spinner", "Gender")
        )

    def _local_xml_allows_gmail_username_entry(self, xml: str) -> bool:
        """True only for Google signup's Gmail username page, never generic email setup."""
        if not xml:
            return False
        labels = " ".join(
            (node.get("text") or node.get("hint") or node.get("content-desc") or "").lower()
            for node in self._node_attrs(xml)
        )
        if "add your email address" in labels and "manual setup" in labels:
            return False
        return any(
            marker in labels
            for marker in (
                "create a gmail address",
                "gmail address",
                "choose your gmail address",
                "create your own gmail address",
                "pick a gmail address",
                "username",
            )
        )

    def _local_xml_has_selected_gmail_suggestion(self, xml: str) -> bool:
        """True for Google's Gmail suggestion-choice page with no username field.

        On this screen Google pre-selects a generated Gmail address and exposes a
        bottom Next button. There is no EditText yet, so trying to type our own
        username loops forever. Accepting the selected suggestion is safe for the
        legal checkpoint flow and avoids logging the generated address.
        """
        if not xml:
            return False
        nodes = list(self._node_attrs(xml))
        labels = " ".join(
            (node.get("text") or node.get("hint") or node.get("content-desc") or "").lower()
            for node in nodes
        )
        has_edittext = any(node.get("class") == "android.widget.EditText" for node in nodes)
        return (
            not has_edittext
            and "create an email address" in labels
            and "create a gmail address" in labels
            and "create your own gmail address" in labels
            and any((node.get("text") or "").strip().lower() == "next" for node in nodes)
        )

    @staticmethod
    def _bounds_center(bounds: str) -> tuple[int, int] | None:
        import re
        m = re.search(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds or "")
        if not m:
            return None
        x1, y1, x2, y2 = map(int, m.groups())
        return (x1 + x2) // 2, (y1 + y2) // 2

    async def _tap_node_by_class_and_hint(self, class_name: str, hint_prefix: str) -> bool:
        """Tap first node with matching class and hint/text/description prefix."""
        xml = await self._dump_adb_xml()
        for attrs in self._node_attrs(xml):
            if attrs.get("class") != class_name:
                continue
            label = attrs.get("hint") or attrs.get("text") or attrs.get("content-desc") or ""
            if not label.startswith(hint_prefix):
                continue
            center = self._bounds_center(attrs.get("bounds", ""))
            if not center:
                continue
            await self.action._run_adb("shell", "input", "tap", str(center[0]), str(center[1]), timeout=5)
            return True
        return False

    async def _type_edittext_by_hint(self, hint_prefix: str, value: str) -> bool:
        """Tap an EditText by hint prefix, clear it and type value."""
        tapped = await self._tap_node_by_class_and_hint("android.widget.EditText", hint_prefix)
        if not tapped:
            return False
        await asyncio.sleep(0.2)
        await self.action.clear_field()
        await self.action.type_text(value)
        return True

    async def _check_username_error(self) -> bool:
        """Проверить есть ли retryable ошибка username при вводе Gmail address."""
        texts = await self.action.get_visible_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        return any(kw in all_text for kw in (
            "taken",
            "unavailable",
            "try another",
            "not available",
            "enter a gmail address",
        ))

    # ─────────────────────────────────────────────────────────────
    # SMS retry
    # ─────────────────────────────────────────────────────────────

    _SMS_OPERATORS = ["virtual53", "virtual4", "virtual58", "any"]

    async def _wait_for_sms_with_retry(self) -> str | None:
        """Ждать SMS-код; при таймауме купить новый номер и повторить."""
        if self._is_manual_phone():
            try:
                code = await self._wait_for_manual_sms_code(timeout=600)
                logger.success("Manual SMS code received")
                return code
            except Exception as e:
                logger.error(f"Manual SMS code was not provided: {e}")
                return None

        self._log_step("Waiting for SMS verification code (up to 90s)...")
        try:
            code = await self.sms.wait_for_code(
                order_id=self.phone_data["id"],
                timeout=90,
                poll_interval=3,
            )
            logger.success(f"SMS code received: {code}")
            await self.sms.finish_order(self.phone_data["id"])
            return code
        except TimeoutError:
            pass

        # Перебираем операторов
        failed_op = (self.phone_data or {}).get("operator", "")
        logger.warning(f"SMS timeout on op={failed_op} → rotating operator...")
        try:
            await self.sms.cancel_order(self.phone_data["id"])
        except Exception:
            pass

        ops = [op for op in self._SMS_OPERATORS if op != failed_op]
        for op in ops:
            logger.info(f"Trying operator {op}...")
            try:
                self.phone_data = await self.sms.buy_number(
                    service="google", country="indonesia", operator=op,
                )
            except Exception as e:
                logger.warning(f"  buy failed op={op}: {e}")
                continue

            logger.info(f"New phone: {self.phone_data['phone']} op={op}")
            await self.action.press_back()
            await asyncio.sleep(2)
            await self._do_enter_phone()

            try:
                code = await self.sms.wait_for_code(
                    order_id=self.phone_data["id"],
                    timeout=90,
                    poll_interval=3,
                )
                logger.success(f"SMS code received on op={op}: {code}")
                await self.sms.finish_order(self.phone_data["id"])
                return code
            except TimeoutError:
                logger.warning(f"  SMS timeout on op={op}")
                try:
                    await self.sms.cancel_order(self.phone_data["id"])
                except Exception:
                    pass

        logger.error("SMS code not received after trying all operators")
        return None

    # ─────────────────────────────────────────────────────────────
    # Открытие формы регистрации
    # ─────────────────────────────────────────────────────────────

    async def _open_google_signup(self):
        """Play Store → Sign in → Create account (fallback: Settings)."""
        self._log_step("Opening Google account creation...")

        # Если уже на экране создания аккаунта — ничего не делаем.
        # In local mode this must be ADB-first: UiAutomator2 instrumentation can
        # crash during GMS add-account and Appium find_elements then hangs/fails
        # with POST /element proxy errors.
        if getattr(config, "DEVICE_FARM", "local") == "local":
            xml = await self._dump_adb_xml()
            texts = self._texts_from_adb_xml(xml)
        else:
            texts = await self.action.get_visible_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        if "create your google account" in all_text or "create a google account" in all_text:
            self._log_step("Already on Create Account screen — skipping Play Store open")
            return

        opened = False
        if not getattr(config, "GOOGLE_REGISTER_SKIP_PLAY_STORE", False):
            opened = await self._open_signup_via_play_store()
        if not opened:
            self._log_step("Play Store skip/failed → Settings fallback")
            await self._open_signup_via_settings_fallback()
        await asyncio.sleep(2)

    async def _open_signup_via_play_store(self) -> bool:
        await self.action.open_app("com.android.vending")
        await asyncio.sleep(5)
        pkg = (await self.action.get_current_package() or "").lower()
        if "vending" not in pkg and "gms" not in pkg:
            return False

        # Local Play Store landing is visually stable, while in-flow
        # uiautomator dumps can fail repeatedly for ~minutes before the existing
        # text lookup reaches its fallback. Tap the known Sign in center first on
        # the 1080x2400 local AVD, then verify/continue via package checks below.
        sign_in_found = False
        if getattr(config, "DEVICE_FARM", "").lower() == "local" and "gms" in pkg:
            self._log_step("Already routed to local GMS Sign in; skipping Play Store Sign in lookup")
            sign_in_found = True
        elif getattr(config, "DEVICE_FARM", "").lower() == "local" and "vending" in pkg:
            self._log_step("Local Play Store landing detected; tapping guarded Sign in coordinate")
            await self.action._run_adb("shell", "input", "tap", "540", "1580", timeout=5)
            await asyncio.sleep(2.5)
            sign_in_found = True

        # Ищем Sign in кнопку
        if not sign_in_found:
            sign_in_found = await self.find_and_tap(
                "'Sign in' button in Play Store",
                retries=4,
                pause_after=2.5,
            )
        if not sign_in_found:
            # Пробуем Profile avatar
            await self.find_and_tap(
                "Profile avatar / account icon in Play Store top bar",
                retries=2,
                pause_after=1.5,
            )
            sign_in_found = await self.find_and_tap(
                "'Sign in' button in Play Store",
                retries=3,
                pause_after=2.5,
            )
        if not sign_in_found:
            # Local API 36 Play Store landing can expose the Sign in button while
            # in-flow uiautomator dumps intermittently fail/return empty. Keep this
            # fallback narrowly scoped to the unauthenticated Play Store landing on
            # the known 1080x2400 emulator profile.
            if getattr(config, "DEVICE_FARM", "").lower() == "local" and "vending" in pkg:
                self._log_step("Play Store Sign in text lookup failed; using guarded local coordinate fallback")
                await self.action._run_adb("shell", "input", "tap", "540", "1580", timeout=5)
                await asyncio.sleep(2.5)
                sign_in_found = True
            else:
                return False

        await asyncio.sleep(4)

        # ADB text lookup can report a successful tap from stale/wrong bounds while
        # the Play Store landing remains visible. If we are still in Play Store on
        # the local emulator after the reported tap, retry the proven button center.
        if getattr(config, "DEVICE_FARM", "").lower() == "local":
            post_sign_pkg = (await self.action.get_current_package() or "").lower()
            if "vending" in post_sign_pkg:
                self._log_step("Still on Play Store after Sign in tap; retrying guarded local coordinate fallback")
                await self.action._run_adb("shell", "input", "tap", "540", "1580", timeout=5)
                await asyncio.sleep(4)
                post_retry_pkg = (await self.action.get_current_package() or "").lower()
                if "vending" in post_retry_pkg:
                    return False

        # Play Store Sign in can route to Android Settings' account-type picker
        # before the Google create-account form. Hand that screen to the existing
        # Settings navigator instead of polling for a Create account link that is
        # not present on the picker.
        if getattr(config, "DEVICE_FARM", "").lower() == "local":
            routed_pkg = (await self.action.get_current_package() or "").lower()
            if "settings" in routed_pkg:
                self._log_step("Play Store Sign in routed to Settings account picker; selecting Google there")
                await self._navigate_settings_to_google_create()
                return True

        # Экран "Sign in with ease" — нажать SKIP чтобы перейти к Sign in форме
        for skip_label in ["SKIP", "Skip"]:
            if await self.tap_text(skip_label, pause=2.0):
                self._log_step(f"Skipped 'Sign in with ease' screen via '{skip_label}'")
                await asyncio.sleep(3)
                break

        # Local GMS sign-in screen can be visible while uiautomator dumps fail
        # indefinitely. The Create account link and personal-use menu item are
        # stable on the 1080x2400 local AVD; tap them before expensive/flaky text
        # lookup. Coordinates verified from live screenshot at GMS Sign in.
        if getattr(config, "DEVICE_FARM", "").lower() == "local":
            gms_pkg = (await self.action.get_current_package() or "").lower()
            if "gms" in gms_pkg:
                self._log_step("Local GMS Sign in detected; tapping guarded Create account coordinate sequences")
                # First try the no-keyboard Sign in layout: the Create account link is
                # near the bottom of the 1080x2400 local AVD. In live runs this tap can
                # also focus the Email/phone field and bring up the keyboard instead of
                # opening the menu, so follow with the keyboard-visible Create account
                # sequence observed on the same GMS screen. If the first sequence already
                # reached the name form, the second pair lands on inert whitespace.
                await self.action._run_adb("shell", "input", "tap", "197", "1176", timeout=5)
                await asyncio.sleep(1.0)
                await self.action._run_adb("shell", "input", "tap", "240", "1235", timeout=5)
                await asyncio.sleep(1.5)
                await self.action._run_adb("shell", "input", "tap", "197", "1222", timeout=5)
                await asyncio.sleep(1.0)
                await self.action._run_adb("shell", "input", "tap", "315", "1356", timeout=5)
                self._local_expect_name_after_gms_create = True
                await asyncio.sleep(4)
                return True

        # Create account
        create_found = await self.find_and_tap(
            "'Create account' link or button at bottom-left of Google sign-in screen",
            retries=10,
            pause_after=2.0,
        )
        if not create_found:
            return False

        # For myself
        await asyncio.sleep(2)
        await self.find_and_tap(
            "'For my personal use' or 'For myself' option in dropdown",
            retries=4,
            pause_after=2.5,
        )
        await asyncio.sleep(4)
        return True

    async def _open_signup_via_settings_fallback(self):
        await self.action.open_settings("ADD_ACCOUNT_SETTINGS")
        await asyncio.sleep(2)
        await self._navigate_settings_to_google_create()

    # ─────────────────────────────────────────────────────────────
    # Навигация Settings → Add Account → Google → Create Account
    # ─────────────────────────────────────────────────────────────

    async def _navigate_settings_to_google_create(self):
        """Прямая навигация Settings → Add account → Google → Create account."""
        action = self.action

        # Принудительно portrait
        await action.force_portrait()
        await asyncio.sleep(1.0)

        # Проверить текущий экран
        pkg = (await action.get_current_package() or "").lower()
        act = (await action.get_current_activity() or "").lower()
        self._log_step(f"Current: pkg={pkg} act={act}")

        # Диагностика: получить все видимые тексты. В локальном API 36 current_activity
        # часто пустой, поэтому наличие списка Exchange/Google/IMAP/POP3 считаем
        # надёжным признаком экрана выбора типа аккаунта.
        texts = []
        try:
            texts = await self.get_texts()
            self._log_step(f"Visible texts ({len(texts)}): {[t[0] for t in texts[:30]]}")
        except Exception as _e:
            self._log_step(f"diag error: {_e}")

        google_rows = [(t, x, y) for t, x, y in texts if t.strip().lower() == "google"]
        account_type_markers = {"exchange", "personal (imap)", "personal (pop3)"}
        if (
            getattr(config, "DEVICE_FARM", "").lower() == "local"
            and "settings" in pkg
            and not texts
            and not act
        ):
            # Android 16 local Settings account-type picker can be plainly visible
            # while uiautomator/text extraction returns an empty hierarchy. The
            # Google row is stable on the 1080x2400 emulator at y≈500; keep this
            # scoped to the blank local Settings account picker path.
            self._log_step("Settings account picker text dump empty; using guarded local Google row fallback")
            await action._run_adb("shell", "input", "tap", "285", "500", timeout=5)
            await asyncio.sleep(4)
            await self._tap_create_account_and_for_myself(action)
            return
        if google_rows and any(t.strip().lower() in account_type_markers for t, _, _ in texts):
            _, gx, gy = google_rows[0]
            self._log_step(f"Account type picker detected by visible texts; tapping Google @ ({gx},{gy})")
            await action._run_adb("shell", "input", "tap", str(gx), str(gy), timeout=5)
            await asyncio.sleep(4)
            await self._tap_create_account_and_for_myself(action)
            return

        # ── Case 1: уже на экране выбора типа аккаунта ──
        if any(m in act for m in ("chooseaccount", "addaccount", "account")):
            self._log_step(f"On account screen: {act} — looking for Google")
            google_found = (
                await action.tap_by_text("Google", pause=3.0)
                or await action.tap_by_text_scroll("Google", pause=3.0)
            )
            if google_found:
                self._log_step("Tapped Google in account type picker")
                await asyncio.sleep(4)
                await self._tap_create_account_and_for_myself(action)
                return
            else:
                self._log_step("Google not found in account picker")

        # ── Case 2: am start напрямую ──
        intents = [
            "am start -a android.settings.ADD_ACCOUNT_SETTINGS",
            "am start -n com.android.settings/.accounts.AddAccountSettings",
        ]
        for cmd in intents:
            await action._mshell(cmd, timeout=8)
            await asyncio.sleep(3.0)
            cur_pkg = (await action.get_current_package() or "").lower()
            cur_act = (await action.get_current_activity() or "").lower()
            self._log_step(f"After {cmd[:40]}: pkg={cur_pkg} act={cur_act}")
            if "settings" in cur_pkg and any(m in cur_act for m in ("chooseaccount", "addaccount", "account")):
                self._log_step(f"am start → account screen: {cur_act}")
                google_found = (
                    await action.tap_by_text("Google", pause=3.0)
                    or await action.tap_by_text_scroll("Google", pause=3.0)
                )
                if google_found:
                    self._log_step("Tapped Google in account type picker (after am start)")
                    await asyncio.sleep(4)
                    await self._tap_create_account_and_for_myself(action)
                    return
                break

        # ── Case 3: UIScrollable — navigate main Settings ──
        found_acct = False
        for text_variant in (
            "Passwords & accounts",
            "Passwords, passkeys & accounts",
            "Accounts",
        ):
            found_acct = (
                await action.tap_by_text_contains_scroll(text_variant, pause=2.0)
                or await action.scroll_to_text_contains(text_variant, pause=2.0)
            )
            if found_acct:
                self._log_step(f"Found Accounts section: '{text_variant}'")
                break

        if not found_acct:
            # Fallback: swipe + page_source search
            for _ in range(6):
                texts = await action.get_visible_texts()
                for text, cx, cy in texts:
                    if any(kw in text.lower() for kw in ("passwords", "accounts", "passkeys")):
                        self._log_step(f"Found via page_source: '{text}' @ ({cx},{cy})")
                        await action.tap(cx, cy, pause=2.5)
                        found_acct = True
                        break
                if found_acct:
                    break
                await action.swipe_up()
                await asyncio.sleep(1.5)

        if not found_acct:
            self._log_step("Accounts section not found — autopilot will navigate")
            return

        await asyncio.sleep(2.0)
        # Dismiss any Autofill dialog
        for dismiss_label in ("No thanks", "Not now", "Cancel"):
            if await action.tap_by_text(dismiss_label, pause=0.8):
                self._log_step(f"Dismissed dialog: '{dismiss_label}'")
                break

        # Add account
        add_found = (
            await action.tap_by_text("Add account", pause=2.0)
            or await action.tap_by_text_scroll("Add account", pause=2.0)
        )
        if not add_found:
            add_found = await self.find_and_tap(
                "'Add account' button on Passwords & accounts settings page",
                retries=2, pause_after=2.0,
            )
        if not add_found:
            self._log_step("'Add account' not found — autopilot will navigate")
            return

        await asyncio.sleep(1.5)

        # Выбор Google
        google_found = (
            await action.tap_by_text("Google", pause=3.0)
            or await action.tap_by_text_scroll("Google", pause=3.0)
        )
        if not google_found:
            google_found = await self.find_and_tap(
                "'Google' row in 'Add account → select account type' list",
                retries=2, pause_after=3.0,
            )
        if not google_found:
            self._log_step("'Google' not found in account type picker")
            return

        await asyncio.sleep(4)
        await self._tap_create_account_and_for_myself(action)
        self._log_step("Settings → Google Create Account navigation done")

    async def _tap_create_account_and_for_myself(self, action):
        """Tap 'Create account' then 'For my personal use'."""
        # Create account
        created = False
        for label in ["Create account", "Create a Google Account"]:
            if await self.tap_text(label, pause=2.0):
                created = True
                break
        if not created:
            created = await self.find_and_tap(
                "'Create account' link at bottom of Google sign-in screen",
                retries=4, pause_after=2.0,
            )
        if not created:
            self._log_step("Create account control not found; continuing so autopilot can recover")

        # For myself / For my personal use
        await asyncio.sleep(2)
        selected = False
        for label in ["For my personal use", "For myself", "Personal use"]:
            if await self.tap_text(label, pause=3.0):
                self._log_step(f"Selected: '{label}'")
                selected = True
                if getattr(config, "DEVICE_FARM", "local") == "local":
                    self._local_expect_name_after_gms_create = True
                break
        if not selected:
            selected = await self.find_and_tap(
                "'For my personal use' or 'For myself' option in Create account menu",
                retries=2,
                pause_after=3.0,
            )
            if selected:
                self._log_step("Selected personal account option via find_and_tap")
                if getattr(config, "DEVICE_FARM", "local") == "local":
                    self._local_expect_name_after_gms_create = True

    # ─────────────────────────────────────────────────────────────
    # UIAutomator2 stage detection (замена CV)
    # ─────────────────────────────────────────────────────────────

    async def _detect_stage_from_page_source(self) -> str:
        """Определить стадию регистрации через UIAutomator2 page_source."""
        try:
            texts = []
            pkg = ""
            try:
                pkg = (await self.action.get_current_package() or "").lower()
            except Exception as pkg_error:
                logger.debug(f"get_current_package failed during stage detection: {pkg_error}")
            if getattr(config, "DEVICE_FARM", "local") == "local":
                xml = await self._dump_adb_xml()
                texts = self._texts_from_adb_xml(xml)
                if not texts:
                    # Empty local ADB XML normally means "no evidence", but after
                    # password submit the live UI can route back to generic Google
                    # Sign in while the password expected-stage guard is still set.
                    # A narrowly-scoped Appium/text fallback is allowed only to
                    # detect that wrong route; otherwise stale Appium text must not
                    # drive signup stages.
                    if self._local_expect_password_after_email and "settings" not in pkg:
                        try:
                            fallback_texts = await self.action.get_visible_texts()
                        except Exception:
                            fallback_texts = []
                        fallback_all_text = " ".join(t.lower() for t, _, _ in fallback_texts)
                        if (
                            "sign in" in fallback_all_text
                            and "create account" in fallback_all_text
                            and (
                                "email or phone" in fallback_all_text
                                or "enter an email or phone" in fallback_all_text
                            )
                        ):
                            self._log_step("Visible Sign in identifier route beats password expectation; reopening Create account")
                            return "signin_create"
                        if getattr(self, "_local_password_empty_xml_submit_attempts", 0) >= 2:
                            self._log_step("Repeated empty-XML password submits did not advance; reopening Create account")
                            return "signin_create"
                        self._log_step("Local email path reached password screen; XML empty, expecting password stage")
                        return "password"
                    if self._local_expect_email_after_birthday and "settings" not in pkg:
                        self._log_step("Local birthday path reached Gmail username screen; XML empty, expecting email stage")
                        return "email"
                    if self._local_expect_birthday_after_name and "settings" not in pkg:
                        self._log_step("Local name path reached birthday screen; XML empty, expecting birthday stage")
                        return "birthday"
                    if self._local_expect_name_after_gms_create and "settings" not in pkg:
                        self._log_step("Local GMS Create account path reached; XML empty, expecting name stage")
                        return "name"
                    return "settings" if "settings" in pkg else "unknown"
            if not texts:
                texts = await self.get_texts()
            all_text = " ".join(t.lower() for t, _, _ in texts)

            # GMS add-account can land on a recoverable ErrorActivity ("Something
            # went wrong / Please go back and try again") while UiAutomator2 is
            # unhealthy. Classify it explicitly so the local flow reopens signup
            # instead of treating it as unknown and looping on unsafe fallbacks.
            if (
                "gms" in pkg
                and "something went wrong" in all_text
                and "try again" in all_text
            ):
                return "gms_error"

            # Gmail's generic "Add your email address" setup screen is a wrong
            # route for this Google-registration scenario. Do not classify it as
            # the signup username/email stage; stale retries typed birthday data
            # into this field in the failing run.
            if (
                "gm" in pkg
                and "add your email address" in all_text
                and "manual setup" in all_text
            ):
                return "wrong_email_setup"

            # Google sign-in landing screen before account creation menu.
            if "sign in" in all_text and "create account" in all_text:
                return "signin_create"

            # Check for registration completion (не путать с "Create a Google Account")
            if any(kw in all_text for kw in ("account created", "welcome to google",
                                              "your google account is ready")):
                return "done"
            if "google account" in all_text and not any(
                kw in all_text for kw in ("create a google account", "create your google account",
                                          "enter your name", "sign in")
            ):
                return "done"

            # Phone verification code input
            if any(kw in all_text for kw in ("verification code", "enter the code", "6-digit")):
                return "phone_code"

            # Phone number input
            if "phone number" in all_text and "verification" not in all_text:
                return "phone_input"

            # Password
            if any(kw in all_text for kw in ("create password", "confirm password", "strong password")):
                return "password"

            # Email
            if any(kw in all_text for kw in ("gmail address", "username", "email address")):
                return "email"

            # Birthday/gender
            if any(kw in all_text for kw in ("birthday", "date of birth", "month", "year", "gender")):
                return "birthday"

            # Name
            if any(kw in all_text for kw in ("first name", "last name", "enter your name",
                                              "create a google account", "create your google account")):
                return "name"

            # Terms
            if any(kw in all_text for kw in ("privacy policy", "terms of service", "i agree", "agree")):
                return "terms"

            # Extra/skip screens
            if any(kw in all_text for kw in ("skip", "not now", "later", "no thanks", "back up")):
                return "extras"

            # Settings navigation
            if "settings" in pkg:
                return "settings"

        except Exception as e:
            logger.debug(f"_detect_stage_from_page_source failed: {e}")

        return "unknown"

    # ─────────────────────────────────────────────────────────────
    # Данные и утилиты
    # ─────────────────────────────────────────────────────────────

    def _signup_values(self, code: str = "") -> dict[str, str]:
        phone_clean = (self.phone_data or {}).get("phone", "").lstrip("+")
        return {
            "first_name":     self.credentials.get("first_name", ""),
            "last_name":      self.credentials.get("last_name", ""),
            "birth_day":      self.credentials.get("birth_day", ""),
            "birth_month":    self.credentials.get("birth_month", ""),
            "birth_year":     self.credentials.get("birth_year", ""),
            "gender":         self.credentials.get("gender", ""),
            "email_username": self.credentials.get("email_username", ""),
            "email_full":     self.credentials.get("full_email", ""),
            "password":       self.credentials.get("password", ""),
            "phone":          phone_clean,
            "code":           code,
        }

    def _stage_goal(self, stage: str) -> str:
        """Описание цели для стадии (для логов)."""
        goals = {
            "name":     "Fill in first_name and last_name fields, then tap Next",
            "birthday": "Fill in birthday and gender, then tap Next",
            "email":    "Choose/create Gmail address, then tap Next",
            "password": "Type password and confirm, then tap Next",
            "terms":    "Accept all terms",
            "extras":   "Skip optional setup screens",
            "done":     "done",
            "settings": "Navigate Settings → Add Account → Google → Create Account",
            "unknown":  "Identify and progress on current screen",
        }
        return goals.get(stage, goals["unknown"])
