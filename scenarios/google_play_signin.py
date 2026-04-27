"""
Авторизация в Google Play Store.

БЕЗ CV — всё через UIAutomator2 page_source.

Стратегия:
1. Settings → Accounts → Add Account → Google (добавляет аккаунт в Android AccountManager)
2. После добавления открываем Play Store — он должен автоматически найти аккаунт
3. Если Play Store всё ещё показывает Sign in — UIAutomator2 навигация
"""
from __future__ import annotations

import asyncio
import re
from loguru import logger

import config
from scenarios.base import BaseScenario


class GooglePlaySigninScenario(BaseScenario):

    NAME = "google_play_signin"

    async def run(self) -> bool:
        email = config.GOOGLE_EMAIL
        password = config.GOOGLE_PASSWORD

        if not email or not password:
            raise RuntimeError("GOOGLE_EMAIL / GOOGLE_PASSWORD not set")

        logger.info("=" * 55)
        logger.info("  SCENARIO: Google Play Sign-in")
        logger.info(f"  Account: {email}")
        logger.info("=" * 55)

        # ── Предпроверка: Play Store может уже знать об аккаунте ──
        self._log_step("Pre-check: opening Play Store to see if already signed in...")
        await self.action.open_app("com.android.vending")
        await asyncio.sleep(8)
        if await self._is_play_store_ready():
            logger.success("Play Store already signed in")
            return True
        self._log_step("Play Store not ready yet, proceeding with account setup...")

        # ── Шаг 1: Добавить аккаунт через Settings (надёжный путь) ──
        self._log_step("Adding Google account via Settings → Add Account...")
        added = await self._add_account_via_settings(email, password)

        if added:
            self._log_step("Account added — clearing Play Store cache so it auto-picks up account...")
            try:
                await self.action._run_adb("shell", "pm", "clear", "com.android.vending", timeout=15)
            except Exception as e:
                logger.warning(f"pm clear vending failed: {e}")
            await asyncio.sleep(5)
            await self.action.open_app("com.android.vending")
            await asyncio.sleep(20)
            if await self._is_play_store_ready():
                logger.success("Play Store ready after account add + cache clear")
                return True
            # Still sign-in screen — try account picker
            self._log_step("Play Store shows sign-in — trying account picker tap...")
            if await self._try_account_picker(email):
                if await self._is_play_store_ready():
                    logger.success("Play Store ready after account picker tap")
                    return True
        else:
            self._log_step("Settings path failed — trying direct Play Store sign-in...")

        # ── Шаг 2: fallback — Play Store direct sign-in ──
        return await self._run_play_store_signin(email, password)

    # ─────────────────────────────────────────────────────────────
    # Settings → Add Account → Google
    # ─────────────────────────────────────────────────────────────

    async def _add_account_via_settings(self, email: str, password: str) -> bool:
        """
        Открывает Settings → Add Account → Google и проходит Google Sign-In.
        Это добавляет аккаунт в Android AccountManager.
        """
        try:
            opened = await self.action.open_add_account_settings()
            if not opened:
                self._log_step("open_add_account_settings failed")
                return False
        except Exception as e:
            self._log_step(f"Add account settings error: {e}")
            return False

        await asyncio.sleep(3)

        # Navigate Settings → Passwords & accounts → Add account → Google
        google_tapped = await self._navigate_to_add_account_google()
        if not google_tapped:
            self._log_step("Google not found in Add account list")
            return False

        # Deterministic sign-in через UIAutomator2
        return await self._run_signin_flow(email, password)

    async def _run_signin_flow(self, email: str, password: str) -> bool:
        """Deterministic Google sign-in через UIAutomator2 (без CV)."""
        max_steps = 40
        stall_counter = 0
        autofill_back_count = 0

        for step in range(1, max_steps + 1):
            await asyncio.sleep(1.0)

            # Проверяем завершение
            if await self._is_account_added():
                logger.success(f"Account added at step {step}")
                return True

            # Определяем что на экране
            stage = await self.detect_stage_from_page_source()
            self._log_step(f"Step {step}/{max_steps} | stage={stage}")

            # Autofill popup — dismiss
            pkg = (await self.action.get_current_package() or "").lower()
            if "gms" in pkg:
                self._log_step("GMS popup detected — dismissing...")
                for label in ["No thanks", "Skip", "Not now", "Cancel", "Decline"]:
                    if await self.tap_text(label, pause=1.0):
                        self._log_step(f"Dismissed: '{label}'")
                        break
                else:
                    await self.action.press_back()
                    await asyncio.sleep(1)
                autofill_back_count += 1
                if autofill_back_count >= 3:
                    self._log_step("Autofill trap — launching direct Google Sign-In intent")
                    await self._launch_google_signin_direct()
                    autofill_back_count = 0
                continue
            autofill_back_count = 0

            # Действия по стадиям
            ok = await self._execute_stage_action(stage, email, password)
            if ok:
                stall_counter = 0
            else:
                stall_counter += 1

            if stall_counter >= 4:
                self._log_step(f"Stall detected at step {step} — trying UIAutomator fallback")
                await self._uiautomator_input_fallback(email, password)
                stall_counter = 0

        logger.warning(f"Sign-in flow exhausted {max_steps} steps")
        return False

    async def _execute_stage_action(self, stage: str, email: str, password: str) -> bool:
        """Выполнить действие в зависимости от стадии."""
        if stage == "done":
            return True

        if stage in ("google_login", "unknown"):
            # Ищем поле email/password
            if await self._try_enter_email(email):
                await self._press_next()
                return True
            if await self._try_enter_password(password):
                await self._press_next()
                return True
            # Dismiss any popup
            await self.handle_unexpected_popup()
            return False

        if stage == "google_gms":
            # GMS popup
            for label in ["No thanks", "Skip", "Not now"]:
                if await self.tap_text(label, pause=1.0):
                    return True
            await self.action.press_back()
            return True

        if stage == "google_verify":
            # Неожиданная верификация — логируем
            self._log_step("Unexpected verification screen during sign-in")
            return False

        if stage == "settings":
            # Навигация в Settings
            return await self._navigate_to_add_account_google()

        # Неизвестная стадия — пробуем dismiss
        return await self.handle_unexpected_popup()
    async def _try_enter_email(self, email: str) -> bool:
        """Попробовать ввести email в поле."""
        # Способ 1: Engine-agnostic EditText поиск
        clicked = await self._find_and_click_any_edittext(
            hints=["email", "phone", "Email", "Phone"]
        )
        if clicked:
            await asyncio.sleep(0.3)
            await self.action.clear_field()
            await self.action.type_text(email)
            self._log_step(f"Entered email: {email}")
            return True

        # Fallback: page_source
        texts = await self.get_texts()
        for text, cx, cy in texts:
            if any(kw in text.lower() for kw in ("email", "phone", "enter your")):
                if "password" not in text.lower():
                    await self.action.tap(cx, cy, pause=0.5)
                    await asyncio.sleep(0.3)
                    await self.action.clear_field()
                    await self.action.type_text(email)
                    self._log_step(f"Entered email via page_source: '{text}'")
                    return True

        return False

    async def _try_enter_password(self, password: str) -> bool:
        """Попробовать ввести пароль в поле."""
        # Способ 1: Engine-agnostic EditText поиск
        clicked = await self._find_and_click_any_edittext(
            hints=["password", "Password"],
            focused=True
        )
        if clicked:
            await asyncio.sleep(0.3)
            await self.action.clear_field()
            await self.action.type_text(password)
            self._log_step("Entered password")
            return True

        # Fallback: page_source
        texts = await self.get_texts()
        for text, cx, cy in texts:
            if "password" in text.lower() and "enter" in text.lower():
                await self.action.tap(cx, cy, pause=0.5)
                await asyncio.sleep(0.3)
                await self.action.clear_field()
                await self.action.type_text(password)
                self._log_step(f"Entered password via page_source: '{text}'")
                return True

        return False

    async def _press_next(self):
        """Нажать Next/Continue."""
        for label in ["Next", "Continue", "Sign in", "Sign In"]:
            if await self.tap_text(label, pause=1.0):
                self._log_step(f"Pressed '{label}'")
                return
        await self.action.press_enter()
        await asyncio.sleep(1)

    async def _is_account_added(self) -> bool:
        """Проверяет что аккаунт добавлен в AccountManager."""
        pkg = (await self.action.get_current_package() or "").lower()
        if "gms" in pkg:
            return False  # GMS popup — это НЕ успех
        if "settings" in pkg:
            texts = await self.get_texts()
            all_text = " ".join(t.lower() for t, _, _ in texts)
            # Если на экране список аккаунтов с нашим email
            if "@gmail.com" in all_text:
                email_lower = (config.GOOGLE_EMAIL or "").lower()
                if email_lower in all_text:
                    self._log_step(f"Account {config.GOOGLE_EMAIL} found in settings")
                    return True
            # Если на экране "account added" / "done"
            if any(kw in all_text for kw in ("account added", "done", "account created")):
                return True
        if "launcher" in pkg or "home" in pkg:
            return True
        return False

    async def _is_play_store_ready(self) -> bool:
        """Проверяет что Play Store показывает контент (не sign-in)."""
        pkg = (await self.action.get_current_package() or "").lower()
        if "vending" not in pkg:
            return False
        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        # Если видим sign-in — не готово
        if any(kw in all_text for kw in ("sign in", "sign-in", "signin", "log in")):
            return False
        # Если видим контент Play Store — готово
        if any(kw in all_text for kw in ("apps", "games", "search", "install", "open", "update")):
            return True
        return False

    # ─────────────────────────────────────────────────────────────
    # Play Store direct sign-in (fallback)
    # ─────────────────────────────────────────────────────────────

    async def _run_play_store_signin(self, email: str, password: str) -> bool:
        """Открываем Play Store и навигируем sign-in через UIAutomator2."""
        # Закрать WebView если висит
        try:
            pkg = (await self.action.get_current_package() or "").lower()
            if "webview_shell" in pkg or "chromium" in pkg:
                await self.action._run_adb("shell", "am", "force-stop", "org.chromium.webview_shell", timeout=5)
                await asyncio.sleep(1)
        except Exception:
            pass

        await self.action.open_app("com.android.vending")
        await asyncio.sleep(6)

        pkg = (await self.action.get_current_package() or "").lower()
        if "vending" not in pkg and "gms" not in pkg:
            await self.action.open_app("com.android.vending")
            await asyncio.sleep(6)

        if await self._is_play_store_ready():
            logger.success("Play Store already signed in")
            return True

        # Пробуем UIAutomator tap "Sign in"
        if await self.action.uiautomator_tap_by_text("Sign in"):
            self._log_step("UIAutomator tapped 'Sign in' — waiting 40s for OAuth flow...")
            await asyncio.sleep(40)
            if await self._is_play_store_ready():
                logger.success("Play Store ready after UIAutomator sign-in")
                return True
            # OAuth не завершился — пробуем Continue
            await self.tap_text("Continue", pause=20.0)
            if await self._is_play_store_ready():
                logger.success("Play Store ready after Continue tap")
                return True

        # Deterministic sign-in flow
        for step in range(30):
            await asyncio.sleep(1.0)

            if await self._is_play_store_ready():
                logger.success(f"Play Store ready at step {step}")
                return True

            # Dismiss popups
            pkg = (await self.action.get_current_package() or "").lower()
            if "gms" in pkg:
                for label in ["No thanks", "Skip", "Not now", "Cancel"]:
                    if await self.tap_text(label, pause=1.0):
                        break
                else:
                    await self.action.press_back()
                continue

            # Try enter email/password
            if await self._try_enter_email(email):
                await self._press_next()
                continue

            if await self._try_enter_password(password):
                await self._press_next()
                continue

            # Try standard buttons
            for label in ["Sign in", "Sign In", "I agree", "Accept", "Next", "More", "Continue"]:
                if await self.tap_text(label, pause=1.5):
                    break
            else:
                # TAP ANY text that looks like a button
                texts = await self.get_texts()
                for text, cx, cy in texts:
                    text_lower = text.lower()
                    if any(kw in text_lower for kw in ("sign", "agree", "accept", "continue", "next")):
                        await self.action.tap(cx, cy, pause=1.5)
                        break

        logger.warning("Play Store sign-in exhausted 30 steps")
        return False

    async def _try_account_picker(self, email: str) -> bool:
        """Попробовать выбрать аккаунт в picker."""
        tapped = await self.action.uiautomator_tap_by_text("Sign in")
        if not tapped:
            tapped = await self.tap_text("Sign in", pause=3.0)
        if not tapped:
            return False
        await asyncio.sleep(5)

        # Пробуем разные варианты
        email_prefix = email.split("@")[0]
        for text_variant in [email, email_prefix, "Continue"]:
            if await self.tap_text_contains(text_variant, pause=2.5):
                self._log_step(f"Account picker: tapped '{text_variant}'")
                await asyncio.sleep(40)
                return True

        # GMS Autofill: "Continue as [email]"
        if await self.tap_text_contains("Continue as", pause=3.0):
            await asyncio.sleep(40)
            return True

        return False

    async def _uiautomator_input_fallback(self, email: str, password: str):
        """UIAutomator fallback — прямой ввод через EditText. Engine-agnostic."""
        import re

        # Считаем EditText через Appium или ADB
        count = 0

        if hasattr(self.action, 'driver'):
            try:
                from appium.webdriver.common.appiumby import AppiumBy
                def _find_all_edits():
                    els = self.action.driver.find_elements(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiSelector().className("android.widget.EditText")'
                    )
                    return len(els)
                count = await self.action._run(_find_all_edits, timeout=8) or 0
            except Exception:
                pass

        if count == 0:
            # ADB fallback: считаем EditText через uiautomator dump
            try:
                await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
                _xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
                count = _xml.count('class="android.widget.EditText"')
            except Exception:
                count = 0

        if count == 0:
            self._log_step("No EditText fields found in fallback")
            return

        if count == 1:
            # Одно поле — вводим email
            clicked = await self._find_and_click_any_edittext()
            if clicked:
                await self.action.clear_field()
                await self.action.type_text(email)
                self._log_step(f"UIAutomator fallback: typed email in single field")
                await self._press_next()

        elif count >= 2:
            # Два поля — email + password
            clicked = await self._find_and_click_any_edittext()
            if clicked:
                await self.action.clear_field()
                await self.action.type_text(email)
                self._log_step("UIAutomator fallback: typed email")
                # Tab к следующему полю
                await self.action.press_tab()
                await asyncio.sleep(0.3)
                await self.action.clear_field()
                await self.action.type_text(password)
                self._log_step("UIAutomator fallback: typed password")
                await self._press_next()

    async def _launch_google_signin_direct(self) -> bool:
        """Прямой ADB-интент на Google Sign-In activity — обходит Autofill."""
        intents = [
            ["shell", "am", "start", "-W",
             "-n", "com.google.android.gms/.auth.uiflows.addaccount.AccountIntroActivity"],
            ["shell", "am", "start", "-W", "-a", "com.google.android.gms.auth.login.LOGIN",
             "-n", "com.google.android.gms/.auth.uiflows.addaccount.AccountIntroActivity"],
            ["shell", "am", "start", "-W",
             "-n", "com.google.android.gms/.auth.google.signin.activity.GoogleSignInActivity"],
        ]
        for intent in intents:
            try:
                out = await self.action._run_adb(*intent, timeout=10)
                if "Error" not in (out or "") and "Exception" not in (out or ""):
                    self._log_step(f"Direct Google Sign-In intent launched: {' '.join(intent[-2:])}")
                    await asyncio.sleep(4)
                    return True
            except Exception as e:
                self._log_step(f"Intent {intent[-1]} failed: {e}")
        return False
