"""
Сценарий: Установка Clash Royale из Google Play Store.

БЕЗ CV — всё через UIAutomator2 page_source.

Flow:
1. Открываем Play Store → страница Clash Royale
2. Нажимаем Install
3. Ждём окончания установки
4. Открываем игру
"""
import asyncio
from loguru import logger

import config
from scenarios.base import BaseScenario


class InstallGameScenario(BaseScenario):

    NAME = "install_game"
    PACKAGE_NAME = "com.supercell.clashroyale"

    async def run(self):
        """Полный flow установки и запуска Clash Royale."""
        logger.info("=" * 50)
        logger.info("SCENARIO: Install Clash Royale")
        logger.info("=" * 50)

        # ─── Проверяем: может уже установлена? ───
        already_installed = await self.action.is_package_installed(self.PACKAGE_NAME)
        if already_installed:
            logger.info("Clash Royale already installed!")
            await self._launch_game()
            return

        # ─── Шаг 1: Открываем Play Store ───
        self._log_step("Opening Play Store page for Clash Royale...")
        await self.action.open_play_store(self.PACKAGE_NAME)
        await asyncio.sleep(5)

        # ─── Проверка: не требует ли Play Store авторизации ───
        if await self._is_signin_screen():
            self._log_step("Play Store requires sign-in, attempting...")
            await self._attempt_play_store_signin()
            await self.action.open_play_store(self.PACKAGE_NAME)
            await asyncio.sleep(5)

        # ─── Шаг 2: Нажимаем Install ───
        self._log_step("Pressing Install button...")
        install_found = await self.find_and_tap(
            "Install button (green button 'Install' or 'Установить')",
            retries=5,
            pause_after=2.0,
        )

        if not install_found:
            # Уже установлена? Ищем Open
            open_found = await self.find_and_tap(
                "Open button or 'Открыть'",
                retries=2,
                pause_after=2.0,
            )
            if open_found:
                logger.info("Game was already installed, opening...")
                await asyncio.sleep(5)
                return

            # Или есть Accept permissions диалог
            await self.find_and_tap(
                "Accept button on permissions dialog",
                retries=2,
                pause_after=2.0,
            )

            # Пробуем Install ещё раз
            await self.find_and_tap(
                "Install button",
                retries=3,
                pause_after=2.0,
            )

        # ─── Шаг 3: Ждём установки ───
        self._log_step("Waiting for installation to complete...")
        await self._wait_for_installation(timeout=90)

        # ─── Шаг 4: Открываем игру ───
        await self._launch_game()

    async def _wait_for_installation(self, timeout: int = 90):
        """Ждать окончания установки (прогресс → кнопка Open)."""
        elapsed = 0
        poll_interval = 3

        while elapsed < timeout:
            # Ищем кнопку Open (установка завершена)
            if await self.tap_text("Open", pause=2.0):
                logger.success(f"Installation complete! Open button found after {elapsed}s")
                return

            # Проверяем page_source на наличие Open
            texts = await self.get_texts()
            for text, cx, cy in texts:
                if text.lower() in ("open", "открыть"):
                    logger.success(f"Installation complete! (page_source) after {elapsed}s")
                    await self.action.tap(cx, cy, pause=2.0)
                    return

            # Проверяем sign-in экран
            if await self._is_signin_screen():
                self._log_step("Sign-in screen during install — attempting...")
                await self._attempt_play_store_signin()
                await self.action.open_play_store(self.PACKAGE_NAME)
                await asyncio.sleep(5)

            # Обработка попапов
            await self.handle_unexpected_popup()

            logger.debug(f"Install progress ({elapsed}s)...")
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval

        # Если таймаут — пробуем открыть напрямую
        logger.warning("Installation timeout — trying to launch directly...")
        await self._launch_game()

    async def _is_signin_screen(self) -> bool:
        """Проверяет показывает ли Play Store экран sign-in."""
        texts = await self.get_texts()
        all_text = " ".join(t.lower() for t, _, _ in texts)
        return any(kw in all_text for kw in ("sign in", "sign-in", "signin", "log in"))

    async def _attempt_play_store_signin(self):
        """Попытаться войти в Play Store."""
        try:
            from scenarios.google_play_signin import GooglePlaySigninScenario
            signin = GooglePlaySigninScenario(cv=self.cv, action=self.action)
            await signin.run()
        except Exception as e:
            logger.warning(f"Inline Play Store sign-in failed: {e}")

    async def _launch_game(self):
        """Запустить Clash Royale."""
        self._log_step("Launching Clash Royale...")
        await self.action.open_app(self.PACKAGE_NAME)
        await asyncio.sleep(5)

        # Ждём загрузки
        self._log_step("Waiting for game to load...")
        for i in range(12):  # Макс 60 секунд на загрузку
            pkg = (await self.action.get_current_package() or "").lower()
            if "clashroyale" in pkg or "supercell" in pkg:
                # Проверяем тексты на экране
                texts = await self.get_texts()
                all_text = " ".join(t.lower() for t, _, _ in texts)
                if any(kw in all_text for kw in ("tutorial", "clash", "arena", "play")):
                    logger.success(f"Game loaded! ({i * 5}s)")
                    return

            # Обработка попапов при загрузке
            await self.handle_unexpected_popup()

            logger.debug(f"Game loading... ({i * 5}s)")
            await asyncio.sleep(5)

        logger.warning("Game loading timeout — proceeding anyway")
