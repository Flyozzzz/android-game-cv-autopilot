"""
Action Engine — управление Android-устройством через ADB.
Тапы, свайпы, ввод текста, скриншоты, управление приложениями.
"""
import asyncio
import os
import shutil
from loguru import logger

import config
from core.helpers import save_screenshot


class ActionEngine:
    """
    Выполняет действия на Android-устройстве через ADB.
    Подключается к удалённому устройству (Genymotion Cloud)
    или локальному эмулятору.
    """

    def __init__(self, adb_serial: str):
        self.serial = adb_serial
        self._adb_path = shutil.which("adb") or "adb"
        self._screenshot_counter = 0
        self._real_screen_w = config.SCREEN_WIDTH
        self._real_screen_h = config.SCREEN_HEIGHT
        self.trace_enabled = bool(getattr(config, "TRACE_ENABLED", False))
        self.trace_save_screenshots = bool(getattr(config, "TRACE_SAVE_SCREENSHOTS", False))
        self.trace_dir = getattr(config, "TRACE_DIR", "trace")
        if self.trace_enabled and self.trace_save_screenshots:
            os.makedirs(os.path.join(self.trace_dir, "screenshots"), exist_ok=True)

    async def _run_adb(self, *args, timeout: int = None) -> str:
        """
        Выполнить ADB-команду и вернуть stdout.
        """
        timeout = timeout or config.ADB_COMMAND_TIMEOUT
        cmd = [self._adb_path, "-s", self.serial] + list(args)
        cmd_str = " ".join(cmd)
        logger.debug(f"ADB: {cmd_str}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )

            stdout_str = stdout.decode("utf-8", errors="replace").strip()
            stderr_str = stderr.decode("utf-8", errors="replace").strip()

            if proc.returncode != 0 and stderr_str:
                logger.warning(f"ADB stderr: {stderr_str}")

            return stdout_str

        except asyncio.TimeoutError:
            logger.error(f"ADB timeout ({timeout}s): {cmd_str}")
            proc.kill()
            return ""
        except FileNotFoundError:
            logger.error("ADB not found! Install android-tools.")
            return ""

    async def _run_adb_raw(self, *args, timeout: int = None) -> bytes:
        """Выполнить ADB-команду и вернуть сырые байты stdout."""
        timeout = timeout or config.ADB_COMMAND_TIMEOUT
        cmd = [self._adb_path, "-s", self.serial] + list(args)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            return stdout

        except asyncio.TimeoutError:
            logger.error(f"ADB raw timeout ({timeout}s)")
            proc.kill()
            return b""

    # ══════════════════════════════════════════
    # Подключение
    # ══════════════════════════════════════════

    async def connect(self) -> bool:
        """Подключиться к удалённому ADB-серверу."""
        result = await self._run_adb("connect", self.serial, timeout=30)
        connected = "connected" in result.lower() or "already" in result.lower()
        if connected:
            logger.success(f"ADB connected: {self.serial}")
        else:
            logger.error(f"ADB connect failed: {result}")
        return connected

    async def disconnect(self):
        """Отключиться от устройства."""
        await self._run_adb("disconnect", self.serial)
        logger.info(f"ADB disconnected: {self.serial}")

    async def check_connection(self) -> bool:
        """Проверить что устройство доступно."""
        result = await self._run_adb("devices")
        return self.serial in result

    # ══════════════════════════════════════════
    # Скриншоты
    # ══════════════════════════════════════════

    async def screenshot(self) -> bytes:
        """
        Сделать скриншот устройства.
        Возвращает PNG-байты.
        """
        png_bytes = await self._run_adb_raw(
            "exec-out", "screencap", "-p", timeout=10
        )
        if not png_bytes or len(png_bytes) < 100:
            logger.warning("Screenshot seems empty, retrying...")
            await asyncio.sleep(0.5)
            png_bytes = await self._run_adb_raw(
                "exec-out", "screencap", "-p", timeout=10
            )
        self._screenshot_counter += 1
        if png_bytes and len(png_bytes) > 24 and png_bytes[:8] == b'\x89PNG\r\n\x1a\n':
            import struct
            w = struct.unpack('>I', png_bytes[16:20])[0]
            h = struct.unpack('>I', png_bytes[20:24])[0]
            if w > 0 and h > 0:
                self._real_screen_w = w
                self._real_screen_h = h
        if self.trace_enabled and self.trace_save_screenshots and png_bytes:
            self._save_trace_screenshot(png_bytes)
        return png_bytes

    async def screenshot_and_save(self, prefix: str = "screen") -> tuple[bytes, str]:
        """Сделать скриншот и сохранить в файл."""
        data = await self.screenshot()
        filepath = save_screenshot(data, config.SCREENSHOT_DIR, prefix)
        return data, filepath

    # ══════════════════════════════════════════
    # Тапы и жесты
    # ══════════════════════════════════════════

    async def tap(self, x: int, y: int, pause: float = 0.3):
        """Тап по координатам."""
        logger.info(f"TAP ({x}, {y})")
        await self._run_adb("shell", "input", "tap", str(x), str(y))
        if pause > 0:
            await asyncio.sleep(pause)

    async def double_tap(self, x: int, y: int):
        """Двойной тап."""
        await self.tap(x, y, pause=0.1)
        await self.tap(x, y, pause=0.3)

    async def long_press(self, x: int, y: int, duration_ms: int = 1000):
        """Долгое нажатие."""
        logger.info(f"LONG_PRESS ({x}, {y}) {duration_ms}ms")
        await self._run_adb(
            "shell", "input", "swipe",
            str(x), str(y), str(x), str(y), str(duration_ms),
        )
        await asyncio.sleep(0.3)

    async def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
    ):
        """Свайп от точки к точке."""
        logger.info(f"SWIPE ({x1},{y1}) -> ({x2},{y2}) {duration_ms}ms")
        await self._run_adb(
            "shell", "input", "swipe",
            str(x1), str(y1), str(x2), str(y2), str(duration_ms),
        )
        await asyncio.sleep(0.3)

    async def swipe_up(self, duration_ms: int = 400):
        """Свайп вверх (скроллим вниз)."""
        cx = self._real_screen_w // 2
        h = self._real_screen_h
        await self.swipe(cx, int(h * 0.75), cx, int(h * 0.25), duration_ms)

    async def swipe_down(self, duration_ms: int = 400):
        """Свайп вниз (скроллим вверх)."""
        cx = self._real_screen_w // 2
        h = self._real_screen_h
        await self.swipe(cx, int(h * 0.25), cx, int(h * 0.75), duration_ms)

    # ══════════════════════════════════════════
    # Ввод текста и клавиши
    # ══════════════════════════════════════════

    async def type_text(self, text: str, pause: float = 0.3):
        """
        Ввод текста через ADB.
        Экранирует спецсимволы для shell.
        """
        logger.info(f"TYPE: '{text}'")
        # Экранируем проблемные символы
        escaped = text
        for char in " &|;<>()$`\\\"'":
            escaped = escaped.replace(char, f"\\{char}")
        # Пробелы → %s для ADB input text
        escaped = escaped.replace("\\ ", "%s")

        await self._run_adb("shell", "input", "text", escaped)
        if pause > 0:
            await asyncio.sleep(pause)

    async def press_key(self, keycode: str):
        """Нажать кнопку по keycode (KEYCODE_BACK, KEYCODE_ENTER, etc.)."""
        logger.debug(f"KEY: {keycode}")
        await self._run_adb("shell", "input", "keyevent", keycode)
        await asyncio.sleep(0.2)

    async def press_back(self):
        """Кнопка Назад."""
        await self.press_key("KEYCODE_BACK")

    async def press_home(self):
        """Кнопка Домой."""
        await self.press_key("KEYCODE_HOME")

    async def press_enter(self):
        """Кнопка Enter."""
        await self.press_key("KEYCODE_ENTER")

    async def press_tab(self):
        """Кнопка Tab (переключить поле)."""
        await self.press_key("KEYCODE_TAB")

    async def press_delete(self, count: int = 1):
        """Удалить символы (Backspace)."""
        for _ in range(count):
            await self.press_key("KEYCODE_DEL")

    async def clear_field(self, max_chars: int = 50):
        """Очистить текущее поле ввода."""
        # Ctrl+A
        await self._run_adb("shell", "input", "keyevent", "--longpress", "KEYCODE_DEL")
        await asyncio.sleep(0.2)
        await self.press_delete(max_chars)

    # ══════════════════════════════════════════
    # Управление приложениями
    # ══════════════════════════════════════════

    async def open_app(self, package: str, activity: str = ""):
        """Открыть приложение."""
        logger.info(f"OPEN APP: {package}")
        if activity:
            await self._run_adb(
                "shell", "am", "start", "-n", f"{package}/{activity}"
            )
        else:
            await self._run_adb(
                "shell", "monkey", "-p", package,
                "-c", "android.intent.category.LAUNCHER", "1",
            )
        await asyncio.sleep(1)

    async def force_stop_app(self, package: str):
        """Принудительно остановить приложение."""
        await self._run_adb("shell", "am", "force-stop", package)

    async def uiautomator_tap_by_text(self, text: str) -> bool:
        """Find element by exact text via UIAutomator dump and tap its center."""
        import re
        try:
            await self._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            xml = await self._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            pattern = rf'text="{re.escape(text)}"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
            m = re.search(pattern, xml)
            if m:
                x = (int(m.group(1)) + int(m.group(3))) // 2
                y = (int(m.group(2)) + int(m.group(4))) // 2
                logger.info(f"UIAutomator tap '{text}' at ({x}, {y})")
                await self._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                return True
        except Exception as e:
            logger.warning(f"uiautomator_tap_by_text('{text}') failed: {e}")
        return False

    # ══════════════════════════════════════════
    # UIAutomator2-совместимые методы (интерфейс как у AppiumActionEngine)
    # Используются сценариями через BaseScenario — работают на ADB без Appium.
    # ══════════════════════════════════════════

    async def _run(self, func, timeout: int = None):
        """Выполнить синхронную функцию в executor (совместимость с AppiumActionEngine)."""
        timeout = timeout or config.ADB_COMMAND_TIMEOUT
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, func),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"ADB run timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.warning(f"ADB run error: {e}")
            return None

    async def _mshell(self, command: str, timeout: int = 5) -> str:
        """Обёртка для shell-команды через ADB."""
        return await self._run_adb("shell", command, timeout=timeout)

    async def tap_by_text(self, text: str, pause: float = 1.5) -> bool:
        """Найти элемент по точному тексту через UIAutomator dump и тапнуть."""
        ok = await self.uiautomator_tap_by_text(text)
        if ok:
            await asyncio.sleep(pause)
        return ok

    async def tap_by_text_contains(self, text: str, pause: float = 1.5) -> bool:
        """Найти элемент содержащий текст через UIAutomator dump и тапнуть."""
        import re
        try:
            await self._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            xml = await self._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            # Ищем text="" содержащий подстроку (case-insensitive)
            text_lower = text.lower()
            bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
            for node in re.finditer(r'<node\b[^>]*?/?>', xml):
                node_str = node.group(0)
                text_match = re.search(r'text="([^"]*)"', node_str)
                if text_match and text_lower in text_match.group(1).lower():
                    m = bounds_re.search(node_str)
                    if m:
                        x = (int(m.group(1)) + int(m.group(3))) // 2
                        y = (int(m.group(2)) + int(m.group(4))) // 2
                        logger.info(f"UIAutomator tap_contains '{text}' at ({x}, {y})")
                        await self._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                        await asyncio.sleep(pause)
                        return True
            # Fallback: content-desc
            for node in re.finditer(r'<node\b[^>]*?/?>', xml):
                node_str = node.group(0)
                desc_match = re.search(r'content-desc="([^"]*)"', node_str)
                if desc_match and text_lower in desc_match.group(1).lower():
                    m = bounds_re.search(node_str)
                    if m:
                        x = (int(m.group(1)) + int(m.group(3))) // 2
                        y = (int(m.group(2)) + int(m.group(4))) // 2
                        logger.info(f"UIAutomator tap_contains (desc) '{text}' at ({x}, {y})")
                        await self._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                        await asyncio.sleep(pause)
                        return True
        except Exception as e:
            logger.warning(f"tap_by_text_contains('{text}') failed: {e}")
        return False

    async def get_visible_texts(self) -> list[tuple[str, int, int]]:
        """Получить все видимые тексты через UIAutomator dump. Возвращает [(text, cx, cy), ...]."""
        import re
        try:
            await self._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            xml = await self._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            results = []
            bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
            for node in re.finditer(r'<node\b[^>]*?/?>', xml):
                node_str = node.group(0)
                text_match = re.search(r'text="([^"]*)"', node_str)
                if text_match and text_match.group(1):
                    text = text_match.group(1)
                    m = bounds_re.search(node_str)
                    if m:
                        cx = (int(m.group(1)) + int(m.group(3))) // 2
                        cy = (int(m.group(2)) + int(m.group(4))) // 2
                        results.append((text, cx, cy))
            return results
        except Exception as e:
            logger.warning(f"get_visible_texts() failed: {e}")
            return []

    async def tap_by_text_scroll(self, text: str, pause: float = 1.5) -> bool:
        """Скроллить вниз и искать текст. Тапнуть если найден."""
        for _ in range(8):
            if await self.tap_by_text(text, pause=pause):
                return True
            await self.swipe_up()
            await asyncio.sleep(1.0)
        return False

    async def tap_by_text_contains_scroll(self, text: str, pause: float = 1.5) -> bool:
        """Скроллить вниз и искать текст по подстроке. Тапнуть если найден."""
        for _ in range(8):
            if await self.tap_by_text_contains(text, pause=pause):
                return True
            await self.swipe_up()
            await asyncio.sleep(1.0)
        return False

    async def scroll_to_text_contains(self, text: str, pause: float = 2.0) -> bool:
        """Алиас для tap_by_text_contains_scroll."""
        return await self.tap_by_text_contains_scroll(text, pause=pause)

    async def tap_by_visible_text_contains(self, text: str, pause: float = 1.5) -> bool:
        """Алиас для tap_by_text_contains."""
        return await self.tap_by_text_contains(text, pause=pause)

    async def force_portrait(self) -> bool:
        """Принудительно переключить в portrait-режим."""
        try:
            await self._run_adb("shell", "settings", "put", "system", "user_rotation", "0", timeout=5)
            await self._run_adb("shell", "settings", "put", "system", "accelerometer_rotation", "0", timeout=5)
            logger.info("Force portrait mode")
            return True
        except Exception as e:
            logger.warning(f"force_portrait failed: {e}")
            return False

    async def open_url(self, url: str):
        """Открыть URL в браузере/приложении."""
        logger.info(f"OPEN URL: {url}")
        await self._run_adb(
            "shell", "am", "start",
            "-a", "android.intent.action.VIEW",
            "-d", url,
        )
        await asyncio.sleep(1)

    async def open_play_store(self, package_name: str):
        """Открыть страницу приложения в Google Play Store."""
        await self.open_url(f"market://details?id={package_name}")

    async def open_settings(self, action: str = ""):
        """
        Открыть настройки Android.
        action: ADD_ACCOUNT_SETTINGS, WIFI_SETTINGS, etc.
        """
        if action == "ADD_ACCOUNT_SETTINGS":
            ok = await self.open_add_account_settings()
            if not ok:
                raise RuntimeError(
                    "Could not leave launcher: Add Account / Settings screen did not open. "
                    "Check device (Genymotion) and that com.android.settings is available."
                )
            return
        if action:
            await self._run_adb(
                "shell", "am", "start",
                "-a", f"android.settings.{action}",
            )
        else:
            await self._run_adb(
                "shell", "am", "start",
                "-a", "android.settings.SETTINGS",
            )
        await asyncio.sleep(1)

    async def _foreground_suggests_account_flow(self) -> bool:
        """
        True если на переднем плане не лаунчер, а экран выбора/добавления аккаунта
        (не просто главная панель «Настройки»).
        """
        pkg = (await self.get_current_package() or "").lower()
        act = (await self.get_current_activity() or "").lower()
        blob = f"{pkg} {act}".replace("_", "")
        if not pkg:
            return False
        if "launcher" in pkg:
            return False
        if any(x in pkg for x in ("launcher3", "launcher2", "trebuchet", "nexuslauncher")):
            return False
        if "com.google.android.gms" in pkg:
            return True
        markers = (
            "account",
            "sync",
            "addaccount",
            "chooseaccount",
            "usersettings",
            "credential",
            "signin",
            "subsettings",
        )
        if "com.android.settings" in pkg and any(m in blob for m in markers):
            return True
        return False

    async def open_add_account_settings(self) -> bool:
        """
        Открыть мастер «Добавить аккаунт» (Google). На AOSP/Genymotion неявный intent
        часто молча не срабатывает — перебираем явные activity и SYNC_SETTINGS.
        """
        logger.info("OPEN: Add account / Google account picker (with foreground check)")

        strategies: list[tuple[str, list[str]]] = [
            (
                "ADD_ACCOUNT implicit +W",
                ["shell", "am", "start", "-W", "-a", "android.settings.ADD_ACCOUNT_SETTINGS"],
            ),
            (
                "SYNC_SETTINGS (Accounts & sync)",
                ["shell", "am", "start", "-W", "-a", "android.settings.SYNC_SETTINGS"],
            ),
            (
                "Settings AddAccountSettings activity",
                [
                    "shell",
                    "am",
                    "start",
                    "-W",
                    "-n",
                    "com.android.settings/.accounts.AddAccountSettings",
                ],
            ),
            (
                "Settings AddAccountSettingsActivity",
                [
                    "shell",
                    "am",
                    "start",
                    "-W",
                    "-n",
                    "com.android.settings/.accounts.AddAccountSettingsActivity",
                ],
            ),
            (
                "Settings inner AddAccount",
                [
                    "shell",
                    "am",
                    "start",
                    "-W",
                    "-n",
                    "com.android.settings/.Settings$AddAccountSettingsActivity",
                ],
            ),
        ]

        for label, cmd in strategies:
            await self._run_adb(*cmd, timeout=20)
            await asyncio.sleep(2.5)
            if await self._foreground_suggests_account_flow():
                logger.success(f"Foreground OK after: {label} (pkg={await self.get_current_package()})")
                return True
            logger.warning(
                f"Still not account/settings UI after {label}: "
                f"pkg={await self.get_current_package()!r}"
            )

        return False

    async def install_apk(self, apk_path: str):
        """Установить APK файл."""
        logger.info(f"INSTALL APK: {apk_path}")
        result = await self._run_adb("install", "-r", "-g", apk_path, timeout=60)
        logger.info(f"Install result: {result}")
        return "Success" in result

    async def is_package_installed(self, package: str) -> bool:
        """Проверить установлено ли приложение."""
        result = await self._run_adb("shell", "pm", "list", "packages", package)
        return f"package:{package}" in result

    async def adb_shell_sh(
        self, script: str, timeout: int = 120
    ) -> tuple[int, str, str]:
        """Выполнить `adb shell sh -c '<script>'`. Возвращает (rc, stdout, stderr)."""
        cmd = [self._adb_path, "-s", self.serial, "shell", "sh", "-c", script]
        logger.debug(f"ADB shell sh -c: {script[:200]}{'…' if len(script) > 200 else ''}")
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            out = stdout.decode("utf-8", errors="replace").strip()
            err = stderr.decode("utf-8", errors="replace").strip()
            return proc.returncode or 0, out, err
        except asyncio.TimeoutError:
            logger.error(f"adb shell sh timeout ({timeout}s)")
            return -1, "", "timeout"

    async def push_local_file(
        self, local_path: str, remote_path: str, timeout: int = 600
    ) -> bool:
        """adb push с хоста на устройство."""
        cmd = [self._adb_path, "-s", self.serial, "push", local_path, remote_path]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            err = stderr.decode("utf-8", errors="replace").strip()
            if proc.returncode != 0:
                logger.error(f"adb push failed rc={proc.returncode}: {err}")
                return False
            logger.info(stdout.decode("utf-8", errors="replace").strip()[-500:])
            return True
        except Exception as e:
            logger.error(f"adb push exception: {e}")
            return False

    async def has_genymotion_flash_archive(self) -> bool:
        """Есть ли скрипт прошивки zip (как при drag-and-drop в Genymotion Desktop)."""
        rc, out, _ = await self.adb_shell_sh(
            "test -x /system/bin/flash-archive.sh && echo OK",
            timeout=15,
        )
        return rc == 0 and "OK" in out

    async def adb_root(self) -> str:
        """Попросить adbd в root (на части эмуляторов)."""
        return await self._run_adb("root", timeout=30)

    async def adb_reboot(self):
        """Перезагрузка устройства."""
        await self._run_adb("reboot", timeout=15)

    async def try_flash_genymotion_gapps_zip(self, host_zip: str) -> tuple[bool, str]:
        """
        Прошить zip через /system/bin/flash-archive.sh (классический Genymotion).

        ВНИМАНИЕ: для Genymotion SaaS официально рекомендован только INSTALL GAPPS
        в портале; сторонние OpenGApps zip могут не проходить flash-archive и портить образ.
        """
        if not os.path.isfile(host_zip):
            return False, f"ZIP не найден: {host_zip}"

        if not await self.has_genymotion_flash_archive():
            return (
                False,
                "На образе нет /system/bin/flash-archive.sh — ADB-прошивка zip недоступна",
            )

        logger.warning(
            "Пробуем flash-archive.sh: это обходной путь; для Cloud Genymotion предпочтительно "
            "INSTALL GAPPS в портале (см. support.genymotion.com GApps / SaaS)."
        )

        root_msg = await self.adb_root()
        if root_msg:
            logger.info(f"adb root: {root_msg[:300]}")
        await asyncio.sleep(2)

        remote = "/sdcard/Download/gm_bot_gapps.zip"
        if not await self.push_local_file(host_zip, remote, timeout=900):
            return False, "adb push zip на /sdcard/Download не удался"

        rc, out, err = await self.adb_shell_sh(
            f"/system/bin/flash-archive.sh {remote} 2>&1",
            timeout=600,
        )
        combined = (out + "\n" + err).strip()
        logger.info(f"flash-archive.sh (rc={rc}) tail: {combined[-2500:]}")
        if rc != 0:
            return False, f"flash-archive.sh rc={rc}: {combined[-800:]}"

        logger.info("Перезагрузка после flash-archive…")
        await self.adb_reboot()
        return True, "reboot после flash-archive; переподключи ADB и проверь pm list"

    # ══════════════════════════════════════════
    # Информация о состоянии устройства
    # ══════════════════════════════════════════

    async def get_current_activity(self) -> str:
        """Получить текущую активити (какой экран/приложение на переднем плане)."""
        result = await self._run_adb(
            "shell", "dumpsys", "activity", "activities"
        )
        for line in result.split("\n"):
            if "mResumedActivity" in line or "topResumedActivity" in line:
                return line.strip()
        return ""

    async def get_current_package(self) -> str:
        """Получить package name текущего приложения."""
        result = await self._run_adb("shell", "dumpsys", "window", "windows")
        for line in result.split("\n"):
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                for part in line.split():
                    if "/" in part:
                        pkg = part.split("/")[0].strip("{}")
                        if "." in pkg:
                            return pkg

        # Fallback: на части Android 12/Genymotion окно может быть "null",
        # но resumed activity в dumpsys activity всё ещё доступна.
        activity_line = await self.get_current_activity()
        for part in activity_line.split():
            if "/" in part:
                pkg = part.split("/")[0].strip("{}")
                if "." in pkg:
                    return pkg
        return ""

    async def is_screen_on(self) -> bool:
        """Проверить включён ли экран."""
        result = await self._run_adb("shell", "dumpsys", "power")
        return "mWakefulness=Awake" in result

    async def wake_up(self):
        """Включить экран если выключен."""
        if not await self.is_screen_on():
            await self.press_key("KEYCODE_WAKEUP")
            await asyncio.sleep(0.5)

    async def get_screen_resolution(self) -> tuple[int, int]:
        """Получить разрешение экрана."""
        result = await self._run_adb("shell", "wm", "size")
        # Physical size: 1080x2400
        if "x" in result:
            parts = result.split(":")[-1].strip().split("x")
            return int(parts[0]), int(parts[1])
        return config.SCREEN_WIDTH, config.SCREEN_HEIGHT

    async def get_device_info(self) -> dict:
        """Получить информацию об устройстве."""
        model = await self._run_adb("shell", "getprop", "ro.product.model")
        android = await self._run_adb("shell", "getprop", "ro.build.version.release")
        sdk = await self._run_adb("shell", "getprop", "ro.build.version.sdk")
        return {
            "model": model,
            "android_version": android,
            "sdk_version": sdk,
            "serial": self.serial,
        }

    # ══════════════════════════════════════════
    # Ожидание
    # ══════════════════════════════════════════

    async def wait_for_app(self, package: str, timeout: int = 30) -> bool:
        """Ждать пока приложение не окажется на переднем плане."""
        elapsed = 0
        while elapsed < timeout:
            current = await self.get_current_package()
            if package in current:
                return True
            await asyncio.sleep(1)
            elapsed += 1
        return False

    def _save_trace_screenshot(self, png_bytes: bytes):
        try:
            filename = f"screen_{self._screenshot_counter:05d}.png"
            path = os.path.join(self.trace_dir, "screenshots", filename)
            with open(path, "wb") as f:
                f.write(png_bytes)
        except Exception as e:
            logger.debug(f"Failed to save trace screenshot: {e}")
