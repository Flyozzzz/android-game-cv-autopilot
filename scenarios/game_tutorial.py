"""
Сценарий: Прохождение туториала Clash Royale и регистрация.

БЕЗ CV — всё через UIAutomator2 page_source.

Flow:
1. Пропуск/прохождение обучающих экранов
2. Обязательный tutorial-бой
3. Выбор имени игрока
4. Выход в главное меню
"""
import asyncio
import random
from loguru import logger

from scenarios.base import BaseScenario
import config


class GameTutorialScenario(BaseScenario):

    NAME = "game_tutorial"

    async def run(self):
        """Полный flow туториала Clash Royale."""
        logger.info("=" * 50)
        logger.info("SCENARIO: Clash Royale Tutorial")
        logger.info("=" * 50)

        # ─── Шаг 1: Убедиться что Clash Royale установлена и запущена ───
        self._log_step("Ensuring Clash Royale is running...")
        installed = await self.action.is_package_installed("com.supercell.clashroyale")
        if not installed:
            logger.warning("is_package_installed returned False — trying to open anyway...")
        pkg = (await self.action.get_current_package() or "").lower()
        if "clashroyale" not in pkg and "supercell" not in pkg:
            logger.info(f"Not in game (pkg={pkg}), launching Clash Royale...")
            await self.action.open_app("com.supercell.clashroyale")
            await asyncio.sleep(20)
        await self.dismiss_popups(max_attempts=5)
        await asyncio.sleep(2)

        # ─── Шаг 2: Tutorial stages ───
        self._log_step("Going through tutorial...")
        max_tutorial_steps = 30
        stuck_counter = 0
        last_screen = ""
        signin_attempts = 0

        for step in range(max_tutorial_steps):
            pkg = (await self.action.get_current_package() or "").lower()
            in_game = "clashroyale" in pkg or "supercell" in pkg

            if not in_game:
                # Не в игре — возможно sign-in экран или popup
                self._log_step(f"Step {step+1}: Not in game (pkg={pkg})")
                await self.handle_unexpected_popup()
                await asyncio.sleep(2)
                continue

            # Получаем тексты экрана
            texts = await self.get_texts()
            all_text = " ".join(t.lower() for t, _, _ in texts)
            visible_texts = [t.lower() for t, _, _ in texts]

            self._log_step(f"Step {step+1}: texts={visible_texts[:5]}")

            # ── Проверяем: вышли из туториала? ──
            if any(kw in all_text for kw in ("clan", "shop", "battle", "cards", "deck")):
                if "tutorial" not in all_text:
                    logger.success("Tutorial complete — reached main menu!")
                    return

            # ── Sign-in экран ──
            if any(kw in all_text for kw in ("sign in", "sign-in", "signin", "log in", "play games")):
                signin_attempts += 1
                self._log_step(f"Sign-in screen (attempt {signin_attempts})")
                if signin_attempts > 3:
                    # Застряли — очищаем кэш Play Store и перезапускаем
                    self._log_step("Stuck on sign-in — clearing cache and restarting...")
                    for _ in range(3):
                        await self.action.press_back()
                        await asyncio.sleep(1)
                    try:
                        await self.action._run_adb("shell", "pm", "clear", "com.android.vending", timeout=15)
                        await asyncio.sleep(3)
                        await self.action._run_adb("shell", "am", "force-stop", "com.supercell.clashroyale", timeout=10)
                        await asyncio.sleep(3)
                    except Exception as e:
                        logger.warning(f"Cache clear failed: {e}")
                    self._log_step("Reopening Clash Royale...")
                    await self.action.open_app("com.supercell.clashroyale")
                    await asyncio.sleep(30)
                    signin_attempts = 0
                else:
                    # Пробуем UIAutomator tap "Sign in"
                    signed = await self.action.uiautomator_tap_by_text("Sign in")
                    if not signed:
                        signed = await self.find_and_tap(
                            "Sign in with Google button or Google Play Games sign in button",
                            retries=2, pause_after=8.0,
                        )
                    if signed:
                        await asyncio.sleep(8)
                        # Пробуем тапнуть Continue
                        await self.action.uiautomator_tap_by_text("Continue")
                        await self._try_fill_google_signin_form()
                    if not signed:
                        # Skip / Play as guest
                        await self.find_and_tap(
                            "Skip sign-in button or Play as guest or Cancel",
                            retries=2, pause_after=2.0,
                        )
                stuck_counter = 0
                continue
            signin_attempts = 0

            # ── Поле ввода имени ──
            if any(kw in all_text for kw in ("name", "имя", "enter your name", "choose a name")):
                await self._enter_player_name()
                continue

            # ── Определяем stuck ──
            screen_key = "|".join(visible_texts[:3])
            if screen_key == last_screen:
                stuck_counter += 1
            else:
                stuck_counter = 0
            last_screen = screen_key

            if stuck_counter >= 3:
                logger.warning("Stuck detected — trying random tap or back")
                await self.action.tap(
                    random.randint(200, 880),
                    random.randint(800, 1600),
                )
                await asyncio.sleep(1)
                stuck_counter = 0
                continue

            # ── Ищем кнопки для нажатия ──
            tapped = False
            button_keywords = [
                "ok", "next", "continue", "tap", "play", "start",
                "confirm", "yes", "got it", "close", "done",
            ]
            for text, cx, cy in texts:
                text_lower = text.lower()
                if any(kw in text_lower for kw in button_keywords):
                    self._log_step(f"Tapping '{text}' at ({cx}, {cy})")
                    await self.action.tap(cx, cy, pause=0.5)
                    tapped = True
                    break

            if not tapped:
                # Тапаем по центру экрана (tutorial tap-anywhere)
                logger.debug("No buttons found — tapping center")
                await self.action.tap(
                    config.SCREEN_WIDTH // 2,
                    config.SCREEN_HEIGHT // 2,
                )

            await asyncio.sleep(1.5)

        # ─── Финальная проверка ───
        self._log_step("Tutorial loop finished, checking state...")
        await self.dismiss_popups(max_attempts=3)

    async def _enter_player_name(self):
        """Вести имя игрока."""
        name = f"Player{random.randint(10000, 99999)}"
        self._log_step(f"Entering player name: {name}")

        entered = await self.find_and_type(
            "player name input field (поле ввода имени)",
            name,
            clear_first=True,
            retries=3,
        )

        if not entered:
            await self.action.tap(config.SCREEN_WIDTH // 2, 1200)
            await asyncio.sleep(0.5)
            await self.action.clear_field()
            await self.action.type_text(name)

        await asyncio.sleep(0.5)

        # Подтверждаем имя
        await self.find_and_tap(
            "OK, Confirm, or checkmark button to confirm player name",
            retries=3,
            pause_after=2.0,
        )

        # Может быть "Are you sure?"
        await asyncio.sleep(1)
        await self.find_and_tap(
            "confirmation button (Yes, OK, Confirm) in 'are you sure' dialog",
            retries=2,
            pause_after=2.0,
        )

    async def _try_fill_google_signin_form(self):
        """Если на экране форма Google sign-in — заполняем credentials."""
        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)

        has_email_field = any(
            kw in all_text
            for kw in ("email", "phone", "enter your email", "enter email")
        )
        if not has_email_field:
            return

        self._log_step("Google sign-in form detected — entering credentials...")

        entered = await self.find_and_type(
            "Email or phone input field",
            config.GOOGLE_EMAIL,
            clear_first=True,
            retries=2,
        )
        if not entered:
            await self.action.uiautomator_tap_by_text("Enter your email or phone")
            await asyncio.sleep(0.5)
            await self.action.type_text(config.GOOGLE_EMAIL)

        await asyncio.sleep(1)
        # Next
        next_tapped = await self.find_and_tap("Next button", retries=2, pause_after=3.0)
        if not next_tapped:
            await self.action.press_enter()
        await asyncio.sleep(4)

        # Пароль
        await self.find_and_type(
            "Password input field",
            config.GOOGLE_PASSWORD,
            clear_first=True,
            retries=2,
        )
        await asyncio.sleep(1)
        next_tapped2 = await self.find_and_tap("Next button", retries=2, pause_after=5.0)
        if not next_tapped2:
            await self.action.press_enter()
        await asyncio.sleep(8)
        self._log_step("Credentials submitted, waiting for auth...")
