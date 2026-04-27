"""
Сценарий: Вход в СУЩЕСТВУЮЩИЙ Google-аккаунт.
Используется ТОЛЬКО если аккаунт уже зарегистрирован.

БЕЗ CV — всё через UIAutomator2 + UIScrollable (LambdaTest-safe).
НЕ используем page_source (HANG) и mobile:shell uiautomator dump (HANG).
"""
import asyncio
from loguru import logger
from appium.webdriver.common.appiumby import AppiumBy

from scenarios.base import BaseScenario
from services.sms_service import SMSService
import config


class GoogleLoginScenario(BaseScenario):

    NAME = "google_login"

    def __init__(self, cv, action, sms_service: SMSService = None, phone_data: dict = None):
        super().__init__(cv, action)
        self.sms = sms_service
        self.phone_data = phone_data

    async def _find_element(self, selector: str, timeout: int = 10):
        """Find element via UIAutomator2 selector (LambdaTest-safe)."""
        try:
            return await self.action._run(
                lambda: self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector),
                timeout=timeout,
            )
        except Exception:
            return None

    async def _find_by_xpath(self, xpath: str, timeout: int = 10):
        """Find element via XPath (works for WebView EditTexts)."""
        try:
            return await self.action._run(
                lambda: self.action.driver.find_element(AppiumBy.XPATH, xpath),
                timeout=timeout,
            )
        except Exception:
            return None

    async def _scroll_find(self, text: str, timeout: int = 15):
        """Scroll into view and find element by text (LambdaTest-safe)."""
        selector = (
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().text("{text}"))'
        )
        return await self._find_element(selector, timeout)

    async def _scroll_find_contains(self, text: str, timeout: int = 15):
        """Scroll into view and find element containing text."""
        selector = (
            f'new UiScrollable(new UiSelector().scrollable(true))'
            f'.scrollIntoView(new UiSelector().textContains("{text}"))'
        )
        return await self._find_element(selector, timeout)

    async def _type_text_shell(self, text: str):
        """Type text via ADB subprocess (works without --relaxed-security)."""
        import subprocess
        escaped = text.replace(" ", "%s").replace("&", "\\&").replace("'", "\\'")
        device = config.LOCAL_DEVICE or "emulator-5554"
        proc = await asyncio.create_subprocess_exec(
            "adb", "-s", device, "shell", "input", "text", escaped,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.wait()

    async def _wait_for_edittext(self, label: str, timeout: int = 45) -> bool:
        """Wait until Google Sign-In exposes an input field instead of a spinner."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            el = await self._find_by_xpath('//android.widget.EditText', timeout=2)
            if el:
                self._log_step(f"{label} input is ready")
                return True
            await asyncio.sleep(2)
        logger.warning(f"Timed out waiting for {label} input")
        return False

    async def _visible_text_blob(self) -> str:
        try:
            texts = await self.action.get_visible_texts()
            return " ".join(t for t, _, _ in texts).lower()
        except Exception:
            return ""

    async def _wait_for_password_input(self, timeout: int = 45) -> bool:
        """Wait for the password page, without confusing email errors for password."""
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            text_blob = await self._visible_text_blob()
            if "couldn" in text_blob and "find your google account" in text_blob:
                logger.error("Google rejected the email: account not found")
                return False

            password_el = await self._find_by_xpath(
                '//android.widget.EditText[@password="true"]', timeout=2
            )
            if password_el:
                self._log_step("password input is ready")
                return True

            if "password" in text_blob:
                generic_el = await self._find_by_xpath('//android.widget.EditText', timeout=2)
                if generic_el:
                    self._log_step("password input is ready")
                    return True

            await asyncio.sleep(2)

        logger.warning("Timed out waiting for password input")
        return False

    async def _tap_first_edittext_from_adb(self) -> bool:
        """Local fallback: tap first EditText from a fresh ADB UI dump."""
        if getattr(config, "DEVICE_FARM", "local") != "local":
            return False
        import re

        xml = ""
        try:
            await self.action._run_adb(
                "shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15
            )
            xml = await self.action._run_adb(
                "shell", "cat", "/sdcard/uidump.xml", timeout=10
            ) or ""
        except Exception:
            return False

        bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        for node in re.finditer(r"<node\b[^>]*?/?>", xml):
            node_text = node.group(0)
            if 'class="android.widget.EditText"' not in node_text:
                continue
            match = bounds_re.search(node_text)
            if not match:
                continue
            x = (int(match.group(1)) + int(match.group(3))) // 2
            y = (int(match.group(2)) + int(match.group(4))) // 2
            await self.action._run_adb(
                "shell", "input", "tap", str(x), str(y), timeout=5
            )
            await asyncio.sleep(0.3)
            return True
        return False

    async def run(self) -> bool:
        """Вход в существующий Google-аккаунт."""
        logger.info("=" * 50)
        logger.info("SCENARIO: Google Login (existing account)")
        logger.info("=" * 50)

        if not config.GOOGLE_EMAIL or not config.GOOGLE_PASSWORD:
            logger.error("GOOGLE_EMAIL and GOOGLE_PASSWORD must be set!")
            raise RuntimeError("No Google credentials for login")

        # ═══════════════════════════════════════════════════════════
        # Открыть Google Sign-In экран
        # ═══════════════════════════════════════════════════════════
        google_opened = await self._open_google_signin()

        if not google_opened:
            raise RuntimeError("Could not open Google Sign-In screen")

        self._log_step("Waiting for Google Sign-In WebView to load...")
        await self._wait_for_edittext("email", timeout=60)

        # ═══════════════════════════════════════════════════════════
        # Ввод email
        # ═══════════════════════════════════════════════════════════
        self._log_step(f"Entering email: {config.GOOGLE_EMAIL}")
        if not await self._enter_email(config.GOOGLE_EMAIL):
            logger.error("Could not enter Google email")
            return False

        # Next
        await self._press_next()
        await asyncio.sleep(2)

        # Dismiss "Your device works better with a Google Account" dialog
        await self._dismiss_google_dialog()
        if not await self._wait_for_password_input(timeout=45):
            return False

        # The same dialog may appear after the password page starts loading.
        await self._dismiss_google_dialog()
        await asyncio.sleep(2)

        # ═══════════════════════════════════════════════════════════
        # Ввод пароля
        # ═══════════════════════════════════════════════════════════
        self._log_step("Entering password...")
        if not await self._enter_password(config.GOOGLE_PASSWORD):
            logger.error("Could not enter Google password")
            return False

        # Next
        await self._press_next()
        await asyncio.sleep(3)

        # ═══════════════════════════════════════════════════════════
        # 2FA если нужно
        # ═══════════════════════════════════════════════════════════
        await asyncio.sleep(3)
        if await self._is_2fa_screen():
            if self.sms and self.phone_data:
                await self._handle_2fa()

        # ═══════════════════════════════════════════════════════════
        # Согласия / промежуточные экраны после пароля
        # Google показывает: "Find My Device", "Add phone number",
        # "Add recovery email", "I agree", "Accept" и т.д.
        # ═══════════════════════════════════════════════════════════
        dismiss_buttons = [
            # Skip / Not now — для "Find My Device", "Add phone number", "Add recovery email"
            "Skip", "Not now", "No thanks",
            # Accept / Agree — для Terms of Service
            "I agree", "I Agree", "AGREE", "Accept", "accept",
            # Close — для информационных диалогов
            "Close",
            # Turn on / Next — иногда нужно подтвердить
            "Turn on",
        ]

        for _ in range(10):
            clicked = False

            # Попытка 1: XPATH с точным текстом кнопки
            for btn_text in dismiss_buttons:
                el = await self._find_by_xpath(
                    f'//android.widget.Button[@text="{btn_text}"]', timeout=2,
                )
                if el:
                    el.click()
                    self._log_step(f"Dismissed consent screen (XPATH: '{btn_text}')")
                    await asyncio.sleep(2)
                    clicked = True
                    break

            if not clicked:
                # Попытка 2: UiSelector с точным текстом
                for btn_text in dismiss_buttons:
                    el = await self._find_element(
                        f'new UiSelector().text("{btn_text}")', timeout=2,
                    )
                    if el:
                        el.click()
                        self._log_step(f"Dismissed consent screen (UiSelector: '{btn_text}')")
                        await asyncio.sleep(2)
                        clicked = True
                        break

            if not clicked:
                # Попытка 3: textContains для partial match
                for kw in ["agree", "Skip", "skip", "Accept", "Not now", "No thanks", "Close"]:
                    el = await self._find_element(
                        f'new UiSelector().textContains("{kw}")', timeout=2,
                    )
                    if el:
                        el.click()
                        self._log_step(f"Dismissed consent screen (partial: '{kw}')")
                        await asyncio.sleep(2)
                        clicked = True
                        break

            if not clicked:
                # Нет кнопок для нажатия — выходим из цикла
                logger.debug("No consent buttons found — assuming done")
                break

        # Проверяем результат: успех только если аккаунт реально попал в Android AccountManager
        await asyncio.sleep(5)
        try:
            accounts = await self.action._run_adb("shell", "dumpsys", "account", timeout=15) or ""
            if config.GOOGLE_EMAIL.lower() in accounts.lower():
                logger.success("Google Login complete — account found in AccountManager")
                return True
        except Exception as e:
            logger.debug(f"AccountManager post-check failed: {e}")

        pkg = (await self.action.get_current_package() or "").lower()
        if "settings" in pkg or "launcher" in pkg or "vending" in pkg:
            logger.info(f"Login ended in pkg={pkg}, but account not found in AccountManager")
        else:
            logger.info(f"Login post-check: pkg={pkg} (account not added yet)")
        return False

    async def _open_google_signin(self) -> bool:
        """Открыть экран Google Sign-In."""
        import subprocess
        device = config.LOCAL_DEVICE or "emulator-5554"

        # ── Стратегия 1: ADB → Settings ADD_ACCOUNT_SETTINGS → tap Google ──
        self._log_step("Opening Settings ADD_ACCOUNT_SETTINGS via ADB")
        try:
            subprocess.run(
                ["adb", "-s", device, "shell", "am", "start",
                 "-a", "android.settings.ADD_ACCOUNT_SETTINGS"],
                capture_output=True, timeout=10,
            )
            await asyncio.sleep(3)

            # Ищем "Google" в списке типов аккаунтов
            el = await self._find_by_xpath(
                '//android.widget.TextView[@text="Google"]', timeout=10
            )
            if el:
                el.click()
                await asyncio.sleep(3)
                logger.success("Tapped 'Google' via XPATH")
                return True

            # Fallback: UiSelector
            el = await self._find_element(
                'new UiSelector().text("Google")', timeout=10
            )
            if el:
                el.click()
                await asyncio.sleep(3)
                logger.success("Tapped 'Google' via UiSelector")
                return True

            # Fallback: UIScrollable
            el = await self._scroll_find("Google", timeout=10)
            if el:
                el.click()
                await asyncio.sleep(3)
                logger.success("Tapped 'Google' via UIScrollable")
                return True
        except Exception as e:
            logger.debug(f"Settings ADD_ACCOUNT failed: {e}")

        # ── Стратегия 2: ADB GMS activity intent ──
        self._log_step("Trying ADB GMS activity intent")
        for activity in [
            "com.google.android.gms/.auth.uiflows.addaccount.AccountIntroActivity",
            "com.google.android.gms/.auth.login.LoginActivity",
        ]:
            try:
                subprocess.run(
                    ["adb", "-s", device, "shell", "am", "start", "-n", activity],
                    capture_output=True, timeout=10,
                )
                await asyncio.sleep(3)
                cur_pkg = (await self.action.get_current_package() or "").lower()
                if "gms" in cur_pkg or "google" in cur_pkg:
                    logger.success(f"GMS intent worked: {activity}")
                    return True
            except Exception:
                continue

        return False

    async def _enter_email(self, email: str) -> bool:
        """Найти поле email и ввести. Google Sign-In WebView — XPATH работает."""
        # Попытка 1: XPATH identifierId (работает в Google WebView!)
        for xpath in [
            '//android.widget.EditText[@resource-id="identifierId"]',
            '//android.widget.EditText',
        ]:
            el = await self._find_by_xpath(xpath, timeout=10)
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(email)
                self._log_step("Email entered (XPATH EditText)")
                return True

        # Попытка 2: UiSelector fallback
        el = await self._find_element(
            'new UiSelector().className("android.widget.EditText")', timeout=5
        )
        if el:
            el.click()
            await asyncio.sleep(0.3)
            el.clear()
            el.send_keys(email)
            self._log_step("Email entered (UiSelector EditText)")
            return True

        if await self._tap_first_edittext_from_adb():
            await self.action.type_text(email)
            self._log_step("Email entered (ADB EditText)")
            return True

        # Last resort: shell input
        self._log_step("No EditText found — using shell input")
        await self._type_text_shell(email)
        return False

    async def _enter_password(self, password: str) -> bool:
        """Найти поле пароля и ввести. Google Sign-In WebView — XPATH работает."""
        text_blob = await self._visible_text_blob()
        if "couldn" in text_blob and "find your google account" in text_blob:
            logger.error("Refusing to type password into email error screen")
            return False

        # Попытка 1: XPATH password EditText
        for xpath in [
            '//android.widget.EditText[@password="true"]',
            '//android.widget.EditText[@resource-id="password"]',
        ]:
            el = await self._find_by_xpath(xpath, timeout=10)
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(password)
                self._log_step("Password entered (XPATH EditText)")
                return True

        if "password" in text_blob:
            el = await self._find_by_xpath('//android.widget.EditText', timeout=10)
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(password)
                self._log_step("Password entered (XPATH generic password page)")
                return True

        # Попытка 2: UiSelector fallback
        if "password" in text_blob:
            el = await self._find_element(
                'new UiSelector().className("android.widget.EditText")', timeout=5
            )
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(password)
                self._log_step("Password entered (UiSelector EditText)")
                return True

        if "password" in text_blob and await self._tap_first_edittext_from_adb():
            await self.action.type_text(password)
            self._log_step("Password entered (ADB EditText)")
            return True

        # Last resort: shell input
        self._log_step("No EditText found — using shell input")
        await self._type_text_shell(password)
        return False

    async def _dismiss_google_dialog(self):
        """Dismiss 'Your device works better with a Google Account' dialog."""
        el = await self._find_by_xpath(
            '//android.widget.Button[@text="Close"]', timeout=2,
        )
        if el:
            el.click()
            self._log_step("Dismissed Google account dialog")
            await asyncio.sleep(1)
            return True
        return False

    async def _press_next(self):
        """Нажать кнопку NEXT. Google Sign-In WebView: bounds=[796,2179][1027,2305] → center (911, 2242)."""
        import subprocess
        device = config.LOCAL_DEVICE or "emulator-5554"

        # Попытка 1: XPATH с text="NEXT" (Google WebView показывает кнопки с CAPS)
        for xpath in [
            '//android.widget.Button[@text="NEXT"]',
            '//android.widget.Button[@text="Next"]',
        ]:
            el = await self._find_by_xpath(xpath, timeout=3)
            if el:
                el.click()
                self._log_step("Pressed 'NEXT' (XPATH)")
                return

        # Попытка 2: UiSelector
        for text in ["NEXT", "Next"]:
            el = await self._find_element(
                f'new UiSelector().text("{text}")', timeout=3,
            )
            if el:
                el.click()
                self._log_step(f"Pressed '{text}' (UiSelector)")
                return

        # Попытка 3: ADB tap по координатам NEXT кнопки
        # bounds=[796,2179][1027,2305] → center (911, 2242)
        next_positions = [
            (911, 2242),  # confirmed center from XPATH dump
            (900, 2200),  # fallback
            (911, 2260),  # fallback slightly lower
        ]
        for x, y in next_positions:
            self._log_step(f"Tapping NEXT at ({x}, {y})")
            subprocess.run(
                ["adb", "-s", device, "shell", "input", "tap", str(x), str(y)],
                capture_output=True, timeout=5,
            )
            await asyncio.sleep(3)

            # Dismiss dialog if it appeared
            await self._dismiss_google_dialog()

            # Проверяем: экран изменился?
            try:
                el = await self._find_by_xpath(
                    '//android.widget.EditText', timeout=2,
                )
                if el:
                    self._log_step(f"EditText found after tap at ({x}, {y}) — screen changed")
                    return
            except Exception:
                pass

        # Fallback: Enter key
        self._log_step("No native NEXT button — pressing Enter")
        subprocess.run(
            ["adb", "-s", device, "shell", "input", "keyevent", "66"],
            capture_output=True, timeout=5,
        )
        await asyncio.sleep(1)

    async def _is_2fa_screen(self) -> bool:
        """Проверить видна ли 2FA форма."""
        for kw in ["verify", "2-step", "phone number", "verification code"]:
            try:
                el = await self._find_element(
                    f'new UiSelector().textContains("{kw}")', timeout=3
                )
                if el:
                    return True
            except Exception:
                pass
        return False

    async def _handle_2fa(self):
        """Handle SMS verification during login."""
        phone = self.phone_data["phone"]

        # Вводим номер телефона
        try:
            el = await self._find_element(
                'new UiSelector().className("android.widget.EditText")', timeout=10
            )
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(phone.lstrip("+"))
        except Exception:
            await self._type_text_shell(phone.lstrip("+"))

        await self._press_next()
        await asyncio.sleep(5)

        code = await self.sms.wait_for_code(
            order_id=self.phone_data["id"],
            timeout=60,
        )

        # Вводим код
        try:
            el = await self._find_element(
                'new UiSelector().className("android.widget.EditText")', timeout=10
            )
            if el:
                el.click()
                await asyncio.sleep(0.3)
                el.clear()
                el.send_keys(code)
        except Exception:
            await self._type_text_shell(code)

        await self._press_next()
        await self.sms.finish_order(self.phone_data["id"])
