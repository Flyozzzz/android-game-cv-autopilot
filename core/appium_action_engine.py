"""
Action Engine via Appium — управление реальным Android-устройством (BrowserStack).
Полностью совместим по интерфейсу с ActionEngine (ADB-версия).
"""
from __future__ import annotations

import asyncio
import base64
import os
from functools import partial
from loguru import logger

import config
from core.helpers import save_screenshot


KEYCODE_MAP: dict[str, int] = {
    "KEYCODE_BACK": 4,
    "KEYCODE_HOME": 3,
    "KEYCODE_ENTER": 66,
    "KEYCODE_TAB": 61,
    "KEYCODE_DEL": 67,
    "KEYCODE_WAKEUP": 224,
    "KEYCODE_POWER": 26,
    "KEYCODE_MENU": 82,
    "KEYCODE_SPACE": 62,
    "KEYCODE_A": 29,
}


class AppiumActionEngine:
    """
    Управление Android устройством через Appium WebDriver (BrowserStack App Automate).
    Интерфейс идентичен ActionEngine — сценарии используются без изменений.
    """

    def __init__(self, driver):
        self.driver = driver
        self._screenshot_counter = 0
        self._real_screen_w = config.SCREEN_WIDTH
        self._real_screen_h = config.SCREEN_HEIGHT
        self.trace_enabled = bool(getattr(config, "TRACE_ENABLED", False))
        self.trace_save_screenshots = bool(getattr(config, "TRACE_SAVE_SCREENSHOTS", False))
        self.trace_dir = getattr(config, "TRACE_DIR", "trace")
        if self.trace_enabled and self.trace_save_screenshots:
            os.makedirs(os.path.join(self.trace_dir, "screenshots"), exist_ok=True)

    async def _run(self, func, timeout: int = None):
        """Выполнить синхронный Appium-вызов в executor (не блокируя event loop)."""
        timeout = timeout or config.ADB_COMMAND_TIMEOUT
        loop = asyncio.get_event_loop()
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, func),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Appium timeout ({timeout}s)")
            return None
        except Exception as e:
            logger.warning(f"Appium call error: {e}")
            return None

    # ══════════════════════════════════════════
    # Подключение (сессия уже активна)
    # ══════════════════════════════════════════

    async def connect(self) -> bool:
        farm = getattr(config, "DEVICE_FARM", "appium")
        logger.info(f"Appium session active ({farm}): {self.driver.session_id}")
        return True

    async def disconnect(self):
        pass  # Жизненным циклом управляет BrowserStackFarm

    async def check_connection(self) -> bool:
        result = await self._run(lambda: self.driver.current_package, timeout=10)
        return result is not None

    # ══════════════════════════════════════════
    # Скриншоты — ОТКЛЮЧЕНЫ (LambdaTest Node16 sharp bug)
    # Все методы скриншотов возвращают пустые байты / заглушки.
    # Навигация полностью через UIAutomator2 (tap_by_text, page_source).
    # ══════════════════════════════════════════

    async def screenshot(self) -> bytes:
        """Return PNG bytes using the safest backend for the active farm."""
        farm = getattr(config, "DEVICE_FARM", "local").strip().lower()

        if farm == "local":
            adb_path = os.getenv("ADB_PATH", "/Users/flyoz/Library/Android/sdk/platform-tools/adb")
            device = getattr(config, "LOCAL_DEVICE", "") or os.getenv("LOCAL_DEVICE", "")
            cmd = [adb_path]
            if device:
                cmd += ["-s", device]
            cmd += ["exec-out", "screencap", "-p"]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
                if proc.returncode == 0 and stdout and stdout[:8] == b"\x89PNG\r\n\x1a\n":
                    self._screenshot_counter += 1
                    self._update_screen_size_from_png(stdout)
                    if self.trace_enabled and self.trace_save_screenshots:
                        self._save_trace_screenshot(stdout)
                    return stdout
                logger.warning(f"local screencap failed: {stderr.decode(errors='ignore').strip()}")
            except Exception as e:
                logger.warning(f"local screencap error: {e}")
            return b""

        # LambdaTest's regular screenshot endpoint can hang; viewportScreenshot is
        # the safer vendor extension and returns base64 directly.
        result = await self._run(
            lambda: self.driver.execute_script("mobile: viewportScreenshot"),
            timeout=20,
        )
        if isinstance(result, str) and len(result) > 100:
            try:
                png_bytes = base64.b64decode(result)
                if png_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                    self._screenshot_counter += 1
                    self._update_screen_size_from_png(png_bytes)
                    if self.trace_enabled and self.trace_save_screenshots:
                        self._save_trace_screenshot(png_bytes)
                    return png_bytes
            except Exception as e:
                logger.debug(f"viewportScreenshot decode failed: {e}")

        fallback = await self._run(lambda: self.driver.get_screenshot_as_png(), timeout=20)
        if isinstance(fallback, bytes) and fallback[:8] == b"\x89PNG\r\n\x1a\n":
            self._screenshot_counter += 1
            self._update_screen_size_from_png(fallback)
            if self.trace_enabled and self.trace_save_screenshots:
                self._save_trace_screenshot(fallback)
            return fallback

        return b""

    async def screenshot_and_save(self, prefix: str = "screen") -> tuple[bytes, str]:
        """Take a screenshot and save it under config.SCREENSHOT_DIR."""
        data = await self.screenshot()
        filepath = save_screenshot(data, config.SCREENSHOT_DIR, prefix) if data else ""
        return data, filepath

    # ══════════════════════════════════════════
    # Тапы и жесты
    # ══════════════════════════════════════════

    async def tap(self, x: int, y: int, pause: float = 0.3):
        logger.info(f"TAP ({x}, {y})")
        if getattr(config, "DEVICE_FARM", "local") == "local":
            await self._run_adb("shell", "input", "tap", str(int(x)), str(int(y)), timeout=5)
        else:
            await self._run(lambda: self.driver.tap([(x, y)]), timeout=10)
        if pause > 0:
            await asyncio.sleep(pause)

    async def tap_by_text(self, text: str, pause: float = 1.5) -> bool:
        """Tap element with exact text via UiAutomator2 (no CV needed)."""
        from appium.webdriver.common.appiumby import AppiumBy

        def _find_and_click():
            selector = f'new UiSelector().text("{text}")'
            el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            el.click()

        ok = await self._run(_find_and_click, timeout=10)
        if ok is None:
            logger.debug(f"tap_by_text not found: '{text}'")
            return False
        logger.info(f"TAP BY TEXT: '{text}'")
        if pause > 0:
            await asyncio.sleep(pause)
        return True

    async def tap_by_text_contains(self, text: str, pause: float = 1.5) -> bool:
        """Tap element whose text contains the given substring."""
        from appium.webdriver.common.appiumby import AppiumBy

        def _find_and_click():
            selector = f'new UiSelector().textContains("{text}")'
            el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            el.click()

        ok = await self._run(_find_and_click, timeout=10)
        if ok is None:
            logger.debug(f"tap_by_text_contains not found: '{text}'")
            return False
        logger.info(f"TAP BY TEXT CONTAINS: '{text}'")
        if pause > 0:
            await asyncio.sleep(pause)
        return True

    async def tap_by_text_scroll(self, text: str, pause: float = 1.5) -> bool:
        """Scroll into view and tap element with exact text (UIScrollable)."""
        from appium.webdriver.common.appiumby import AppiumBy

        def _scroll_and_click():
            selector = (
                f'new UiScrollable(new UiSelector().scrollable(true))'
                f'.scrollIntoView(new UiSelector().text("{text}"))'
            )
            el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            el.click()

        ok = await self._run(_scroll_and_click, timeout=15)
        if ok is None:
            logger.debug(f"tap_by_text_scroll not found: '{text}'")
            return False
        logger.info(f"TAP BY TEXT SCROLL: '{text}'")
        if pause > 0:
            await asyncio.sleep(pause)
        return True

    async def tap_by_text_contains_scroll(self, text: str, pause: float = 1.5) -> bool:
        """Scroll into view and tap element whose text contains substring (UIScrollable)."""
        from appium.webdriver.common.appiumby import AppiumBy

        def _scroll_and_click():
            selector = (
                f'new UiScrollable(new UiSelector().scrollable(true))'
                f'.scrollIntoView(new UiSelector().textContains("{text}"))'
            )
            el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            el.click()

        ok = await self._run(_scroll_and_click, timeout=15)
        if ok is None:
            logger.debug(f"tap_by_text_contains_scroll not found: '{text}'")
            return False
        logger.info(f"TAP BY TEXT CONTAINS SCROLL: '{text}'")
        if pause > 0:
            await asyncio.sleep(pause)
        return True

    async def scroll_to_text_contains(self, text: str, pause: float = 2.0) -> bool:
        """
        Прокрутить до элемента c текстом (textContains), перебирая все типы контейнеров.
        Решает проблему когда Settings RecyclerView не помечен как scrollable(true).
        """
        from appium.webdriver.common.appiumby import AppiumBy

        # Все типичные контейнеры в Android Settings
        scrollable_selectors = [
            'new UiScrollable(new UiSelector().scrollable(true))',
            'new UiScrollable(new UiSelector().className("androidx.recyclerview.widget.RecyclerView"))',
            'new UiScrollable(new UiSelector().className("android.widget.RecyclerView"))',
            'new UiScrollable(new UiSelector().className("android.widget.ListView"))',
            'new UiScrollable(new UiSelector().className("android.widget.ScrollView"))',
        ]

        def _try_scroll(scroll_sel: str):
            selector = (
                f'{scroll_sel}'
                f'.setMaxSearchSwipes(30)'
                f'.scrollIntoView(new UiSelector().textContains("{text}"))'
            )
            el = self.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
            el.click()
            return True

        for sel in scrollable_selectors:
            ok = await self._run(lambda s=sel: _try_scroll(s), timeout=20)
            if ok is not None:
                logger.info(f"SCROLL TO TEXT CONTAINS '{text}' via {sel[:50]}")
                if pause > 0:
                    await asyncio.sleep(pause)
                return True
        logger.debug(f"scroll_to_text_contains: '{text}' not found in any container")
        return False

    async def double_tap(self, x: int, y: int):
        await self.tap(x, y, pause=0.1)
        await self.tap(x, y, pause=0.3)

    async def long_press(self, x: int, y: int, duration_ms: int = 1000):
        logger.info(f"LONG_PRESS ({x}, {y}) {duration_ms}ms")
        await self._run(
            lambda: self.driver.tap([(x, y)], duration=duration_ms), timeout=10
        )
        await asyncio.sleep(0.3)

    async def swipe(
        self,
        x1: int, y1: int,
        x2: int, y2: int,
        duration_ms: int = 300,
    ):
        logger.info(f"SWIPE ({x1},{y1}) -> ({x2},{y2}) {duration_ms}ms")
        # Priority 1: mobile:shell input swipe — CONFIRMED ✅ OK on LT (461ms)
        # driver.swipe() HANGS >15s on LambdaTest (triggers server screenshot)
        shell_ok = await self._run(
            lambda: self.driver.execute_script("mobile: shell", {
                "command": "input",
                "args": ["swipe", str(x1), str(y1), str(x2), str(y2), str(duration_ms)],
            }),
            timeout=8,
        )
        if shell_ok is None:
            # Fallback: W3C swipe (may hang on LT, but last resort)
            await self._run(
                lambda: self.driver.swipe(x1, y1, x2, y2, duration_ms), timeout=15
            )
        await asyncio.sleep(0.3)

    def _portrait_dims(self) -> tuple[int, int]:
        """Возвращает (width, height) в portrait-ориентации.
        BrowserStack может вернуть PNG с переставленными осями — исправляем.
        """
        w, h = self._real_screen_w, self._real_screen_h
        # Если ширина > высоты — это landscape или перепутаны оси; переставляем
        if w > h:
            w, h = h, w
        return w, h

    async def force_portrait(self) -> bool:
        """Принудительно переключить в portrait.
        Нужно вызывать перед открытием Settings — BrowserStack/LambdaTest иногда оставляет
        устройство в landscape (rotation=1), что делает Settings RecyclerView 17px высотой.
        """
        if getattr(config, "DEVICE_FARM", "").lower() == "local":
            # Local Appium UiAutomator2 instrumentation is intentionally not used
            # for orientation; recent smoke runs crashed on POST /orientation.
            # ADB coordinate automation assumes portrait dimensions and the AVD is
            # configured portrait, so this is a safe no-op for local runs.
            logger.info("FORCE PORTRAIT skipped for local ADB-first run")
            return True

        # 1) driver.orientation property (W3C) — works on LambdaTest without mobile:shell
        try:
            current = await self._run(lambda: self.driver.orientation, timeout=10)
            if current and str(current).upper() == "PORTRAIT":
                return True
        except Exception:
            pass
        try:
            await self._run(
                lambda: setattr(self.driver, "orientation", "PORTRAIT"), timeout=10
            )
            await asyncio.sleep(1.0)
            logger.info("FORCE PORTRAIT via driver.orientation")
            return True
        except Exception as e:
            logger.debug(f"force_portrait failed: {e}")
            return False

    async def scroll_back_to_text(self, element_id: str, text: str) -> bool:
        """
        mobile:scrollBackTo — BrowserStack-whitelisted команда для прокрутки к тексту.
        element_id: resource-id контейнера (напр. 'com.android.settings:id/recycler_view')
        """
        try:
            result = await self._run(
                lambda: self.driver.execute_script("mobile: scrollBackTo", {
                    "elementId": element_id,
                    "text": text,
                }),
                timeout=15,
            )
            if result is not None:
                logger.info(f"SCROLL BACK TO '{text}' in {element_id!r}")
                return True
        except Exception as e:
            logger.debug(f"scroll_back_to_text failed: {e}")
        return False

    async def swipe_up(self, duration_ms: int = 400):
        w, h = self._portrait_dims()
        cx = w // 2
        await self.swipe(cx, int(h * 0.75), cx, int(h * 0.25), duration_ms)

    async def swipe_down(self, duration_ms: int = 400):
        w, h = self._portrait_dims()
        cx = w // 2
        await self.swipe(cx, int(h * 0.25), cx, int(h * 0.75), duration_ms)

    # ══════════════════════════════════════════
    # Ввод текста и клавиши
    # ══════════════════════════════════════════

    async def type_text(self, text: str, pause: float = 0.3):
        logger.info(f"TYPE: '{text}'")
        typed = False

        # Local emulator path: avoid Appium/mobile:shell entirely. UiAutomator2 is
        # known to crash/hang in this project, while host adb input works once a
        # WebView field is focused.
        if getattr(config, "DEVICE_FARM", "local") == "local":
            try:
                escaped = self._adb_input_text_arg(text)
                ok = await self._run_adb("shell", "input", "text", escaped, timeout=8)
                if ok is not None:
                    typed = True
                    logger.debug("type_text: host adb input text sent")
            except Exception as e:
                logger.debug(f"type_text: host adb input failed: {e}")

        if not typed:
            # Priority 1: mobile:shell input text — OK on remote farms, but not
            # reliable on local UiAutomator2.
            ok = await self._run(
                lambda: self.driver.execute_script("mobile: shell", {
                    "command": "input",
                    "args": ["text", text.replace(" ", "%s")],
                }),
                timeout=8,
            )
            if ok is not None:
                typed = True
                logger.debug("type_text: mobile:shell input text sent")

        if not typed:
            # Priority 2: send_keys on active element
            ok = await self._run(
                lambda: self.driver.switch_to.active_element.send_keys(text),
                timeout=12,
            )
            if ok is not None:
                typed = True
                logger.debug("type_text: send_keys on active_element succeeded")

        if not typed:
            # Priority 3: mobile:type (может упасть с UnicodeIME error — уменьшен timeout до 10s)
            await self._run(
                lambda: self.driver.execute_script("mobile: type", {"text": text}),
                timeout=10,
            )

        if pause > 0:
            await asyncio.sleep(pause)

    async def type_text_via_keycodes(self, text: str):
        """Вводит текст через send_keys на active element — работает на LambdaTest."""
        logger.info(f"TYPE (via send_keys): '{text}'")
        # send_keys handles all chars; no mobile:shell needed
        await self._run(
            lambda: self.driver.switch_to.active_element.send_keys(text),
            timeout=15,
        )
        await asyncio.sleep(0.3)

    async def press_key(self, keycode: str):
        code = KEYCODE_MAP.get(keycode)
        if code is None:
            try:
                code = int(keycode)
            except (ValueError, TypeError):
                logger.warning(f"Unknown keycode: {keycode}")
                return
        logger.debug(f"KEY: {keycode} ({code})")
        if getattr(config, "DEVICE_FARM", "local") == "local":
            await self._run_adb("shell", "input", "keyevent", str(code), timeout=5)
        else:
            # Use native press_keycode — works on LambdaTest without sharp module
            # (mobile:shell hangs for 60s on LT Node 16, so we avoid it)
            await self._run(
                lambda: self.driver.press_keycode(code),
                timeout=5,
            )
        await asyncio.sleep(0.2)

    async def press_back(self):
        await self.press_key("KEYCODE_BACK")

    async def press_home(self):
        await self.press_key("KEYCODE_HOME")

    async def press_enter(self):
        await self.press_key("KEYCODE_ENTER")

    async def press_tab(self):
        await self.press_key("KEYCODE_TAB")

    async def press_delete(self, count: int = 1):
        for _ in range(count):
            await self.press_key("KEYCODE_DEL")

    async def clear_field(self, max_chars: int = 50):
        # Local emulator: use host adb keyevents to avoid UiAutomator2 hangs.
        if getattr(config, "DEVICE_FARM", "local") == "local":
            await self._run_adb("shell", "input", "keyevent", "277", timeout=5)  # CTRL+A
            await asyncio.sleep(0.1)
            await self._run_adb("shell", "input", "keyevent", "67", timeout=5)  # DEL
            await asyncio.sleep(0.2)
            return

        # Use native press_keycode — no mobile:shell needed on LambdaTest
        # Select all (CTRL+A = keycode 277) then DEL
        await self._run(
            lambda: self.driver.press_keycode(277),  # KEYCODE_CTRL_A
            timeout=10,
        )
        await asyncio.sleep(0.1)
        await self._run(
            lambda: self.driver.press_keycode(67),  # KEYCODE_DEL
            timeout=10,
        )
        await asyncio.sleep(0.2)

    # ══════════════════════════════════════════
    # Управление приложениями
    # ══════════════════════════════════════════

    async def open_app(self, package: str, activity: str = ""):
        logger.info(f"OPEN APP: {package}")
        if activity:
            await self._run(
                lambda: self.driver.start_activity(package, activity),
                timeout=20,
            )
        else:
            # activate_app (native Appium)
            ok = await self._run(
                lambda: self.driver.activate_app(package),
                timeout=20,
            )
            if ok is None:
                # Fallback: start_activity с типичными activity именами
                for act in [
                    "com.google.android.finsky.activities.MainActivity",
                    "com.google.android.finsky.MainActivity",
                    ".MainActivity",
                ]:
                    ok = await self._run(
                        lambda p=package, a=act: self.driver.start_activity(p, a),
                        timeout=15,
                    )
                    if ok is not None:
                        logger.info(f"OPEN APP: started via fallback activity {act}")
                        break
                else:
                    logger.warning(f"OPEN APP: {package} — no launchable activity found")
        await asyncio.sleep(5)

    async def force_stop_app(self, package: str):
        await self._run(lambda: self.driver.terminate_app(package), timeout=15)

    async def open_url(self, url: str):
        logger.info(f"OPEN URL: {url}")
        ok = await self._run(
            lambda: self.driver.execute_script(
                "mobile: deepLink",
                {"url": url, "package": "com.android.chrome"},
            ),
            timeout=15,
        )
        if ok is None:
            await self._mshell(f"am start -a android.intent.action.VIEW -d {url!r}")
        await asyncio.sleep(1)

    async def open_play_store(self, package_name: str):
        url = f"market://details?id={package_name}"
        # Use mobile:deepLink — works on LambdaTest (no mobile:shell needed)
        ok = await self._run(
            lambda: self.driver.execute_script("mobile: deepLink", {
                "url": url,
                "package": "com.android.vending",
            }),
            timeout=15,
        )
        if ok is None:
            # Fallback: activate Play Store then _mshell
            await self._run(
                lambda: self.driver.activate_app("com.android.vending"),
                timeout=15,
            )
        await asyncio.sleep(1)

    async def open_settings(self, action: str = ""):
        if action == "ADD_ACCOUNT_SETTINGS":
            ok = await self.open_add_account_settings()
            if not ok:
                raise RuntimeError("Could not open Add Account settings")
            return
        if action:
            # Try deepLink first, then mobile:shell as fallback
            try:
                await self._run(
                    lambda: self.driver.execute_script("mobile: deepLink", {
                        "url": f"android.settings.{action}",
                        "package": "com.android.settings",
                    }),
                    timeout=10,
                )
            except Exception:
                await self._mshell(f"am start -a android.settings.{action}")
        else:
            # Open Settings via activate_app (native Appium, no mobile:shell)
            await self._run(
                lambda: self.driver.activate_app("com.android.settings"),
                timeout=15,
            )
        await asyncio.sleep(1)

    async def _mshell(self, command: str, timeout: int = 5) -> str:
        """ADB shell через Appium mobile:shell.
        На BrowserStack 'adb_shell' отключён — большинство команд (am, pm) упадут.
        На LambdaTest Node 16 — mobile:shell вешается из-за sharp module bug.
        Логируем и возвращаем пустую строку вместо краша.
        Таймаут 5с по умолчанию чтобы не блокировать надолго.
        """
        import shlex

        parts = shlex.split(command.strip())
        if not parts:
            return ""

        # Local emulator: prefer host adb. Appium mobile:shell is much slower here
        # and has been observed to destabilize UiAutomator2 during long signup runs.
        if getattr(config, "DEVICE_FARM", "").strip().lower() == "local":
            return await self._run_adb("shell", *parts, timeout=timeout)

        try:
            result = await self._run(
                lambda: self.driver.execute_script("mobile: shell", {
                    "command": parts[0],
                    "args": parts[1:],
                }),
                timeout=timeout,
            )
            return str(result or "")
        except Exception as e:
            err = str(e)
            if "adb_shell" in err or "insecure feature" in err.lower():
                logger.debug(f"_mshell '{parts[0]}' blocked by BrowserStack (adb_shell disabled) — skipping")
            else:
                logger.debug(f"_mshell '{parts[0]}' failed: {e}")
            return ""

    async def _foreground_suggests_account_flow(self) -> bool:
        # NOTE: current_activity HANGS on LambdaTest — use only current_package
        pkg = (await self.get_current_package() or "").lower()
        if not pkg or "launcher" in pkg:
            return False
        if "com.google.android.gms" in pkg:
            return True
        # Check via UIAutomator: look for "Add account" or "Google" text visible
        if "com.android.settings" in pkg:
            for text in ["Add account", "Google", "Choose account"]:
                el = await self._run(
                    lambda t=text: self.driver.find_element(
                        __import__("appium.webdriver.common.appiumby", fromlist=["AppiumBy"]).AppiumBy.ANDROID_UIAUTOMATOR,
                        f'new UiSelector().text("{t}")'
                    ),
                    timeout=3,
                )
                if el:
                    return True
        return False

    async def open_add_account_settings(self) -> bool:
        """
        Открыть Settings → Add Account → Google.
        Использует mobile:deepLink + UIScrollable (LambdaTest-safe).
        """
        from appium.webdriver.common.appiumby import AppiumBy

        logger.info("OPEN: Add account (deepLink + UIScrollable)")

        # ── Принудительный portrait ──
        await self.force_portrait()
        await asyncio.sleep(0.5)

        # Local emulator: Android settings intents are more reliable via host adb
        # than Appium deepLink/mobile:shell. Try this first and let the generic
        # UIAutomator strategies below select Add account/Google.
        if getattr(config, "DEVICE_FARM", "").strip().lower() == "local":
            try:
                out = await self._run_adb(
                    "shell", "am", "start", "-a", "android.settings.ADD_ACCOUNT_SETTINGS",
                    timeout=8,
                )
                logger.info(f"Local adb ADD_ACCOUNT_SETTINGS: {out[:120]}")
                await asyncio.sleep(3)
            except Exception as e:
                logger.debug(f"Local adb ADD_ACCOUNT_SETTINGS failed: {e}")

        # ── Стратегия 1: mobile:deepLink → ADD_ACCOUNT_SETTINGS ──
        try:
            await self._run(
                lambda: self.driver.execute_script("mobile: deepLink", {
                    "url": "android.settings.ADD_ACCOUNT_SETTINGS",
                    "package": "com.android.settings",
                }),
                timeout=10,
            )
            await asyncio.sleep(3)
            logger.info("Opened ADD_ACCOUNT_SETTINGS via deepLink")
        except Exception as e:
            logger.debug(f"deepLink failed: {e}, trying am start")
            await self._run_adb("shell", "am", "start", "-a", "android.settings.ADD_ACCOUNT_SETTINGS", timeout=5)
            await asyncio.sleep(3)

        # ── Стратегия 2: UIScrollable → "Add account" → "Google" ──
        # На экране Add account должен быть список типов аккаунтов
        # Пробуем сразу тапнуть "Google" (если список уже открыт)
        try:
            el = await self._run(
                lambda: self.driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiScrollable(new UiSelector().scrollable(true))'
                    '.scrollIntoView(new UiSelector().text("Google"))'
                ),
                timeout=15,
            )
            if el:
                el.click()
                await asyncio.sleep(2)
                logger.success("Tapped 'Google' via UIScrollable (direct)")
                return True
        except Exception as e:
            logger.debug(f"UIScrollable 'Google' direct failed: {e}")

        # ── Стратегия 3: Найти "Add account" → тапнуть → найти "Google" ──
        try:
            el = await self._run(
                lambda: self.driver.find_element(
                    AppiumBy.ANDROID_UIAUTOMATOR,
                    'new UiScrollable(new UiSelector().scrollable(true))'
                    '.scrollIntoView(new UiSelector().textContains("Add account"))'
                ),
                timeout=15,
            )
            if el:
                el.click()
                await asyncio.sleep(3)
                logger.info("Tapped 'Add account' via UIScrollable")

                # Теперь ищем "Google" в списке типов аккаунтов
                el2 = await self._run(
                    lambda: self.driver.find_element(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiScrollable(new UiSelector().scrollable(true))'
                        '.scrollIntoView(new UiSelector().text("Google"))'
                    ),
                    timeout=15,
                )
                if el2:
                    el2.click()
                    await asyncio.sleep(2)
                    logger.success("Tapped 'Google' via UIScrollable (after Add account)")
                    return True
        except Exception as e:
            logger.debug(f"UIScrollable Add account → Google failed: {e}")

        # ── Стратегия 4: Settings app → Accounts → Add account → Google ──
        try:
            await self._run(
                lambda: self.driver.activate_app("com.android.settings"),
                timeout=10,
            )
            await asyncio.sleep(2)

            # Ищем "Accounts" / "Passwords & accounts"
            for text in ["Passwords & accounts", "Passwords, passkeys & accounts", "Accounts", "Users & accounts"]:
                try:
                    el = await self._run(
                        lambda t=text: self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiScrollable(new UiSelector().scrollable(true))'
                            f'.scrollIntoView(new UiSelector().textContains("{t}"))'
                        ),
                        timeout=10,
                    )
                    if el:
                        el.click()
                        await asyncio.sleep(2)
                        logger.info(f"Tapped '{text}' in Settings")
                        break
                except Exception:
                    continue

            # Ищем "Add account"
            try:
                el = await self._run(
                    lambda: self.driver.find_element(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiScrollable(new UiSelector().scrollable(true))'
                        '.scrollIntoView(new UiSelector().textContains("Add account"))'
                    ),
                    timeout=10,
                )
                if el:
                    el.click()
                    await asyncio.sleep(2)
            except Exception:
                pass

            # Ищем "Google"
            try:
                el = await self._run(
                    lambda: self.driver.find_element(
                        AppiumBy.ANDROID_UIAUTOMATOR,
                        'new UiScrollable(new UiSelector().scrollable(true))'
                        '.scrollIntoView(new UiSelector().text("Google"))'
                    ),
                    timeout=10,
                )
                if el:
                    el.click()
                    await asyncio.sleep(2)
                    logger.success("Tapped 'Google' via Settings navigation")
                    return True
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"Settings navigation failed: {e}")

        # ── Стратегия 5: GMS прямой intent ──
        for intent in [
            "am start -n com.google.android.gms/.auth.uiflows.addaccount.AccountIntroActivity",
            "am start -a com.google.android.gms.auth.login.LOGIN",
        ]:
            try:
                await self._run_adb("shell", *intent.split(), timeout=5)
                await asyncio.sleep(3)
                pkg = (await self.get_current_package() or "").lower()
                if "gms" in pkg or "google" in pkg:
                    logger.success(f"GMS intent worked: {intent[:50]}")
                    return True
            except Exception:
                continue

        logger.warning("open_add_account_settings: all strategies attempted")
        return True  # Возвращаем True чтобы сценарий попробовал продолжить

    async def install_apk(self, apk_path: str) -> bool:
        logger.info(f"INSTALL APK via Appium: {apk_path}")
        await self._run(lambda: self.driver.install_app(apk_path), timeout=120)
        return True

    async def is_package_installed(self, package: str) -> bool:
        result = await self._run(
            lambda: self.driver.is_app_installed(package), timeout=10
        )
        return bool(result)

    async def uiautomator_tap_by_text(self, text: str) -> bool:
        """Alias for tap_by_text — Appium uses UIAutomator2 natively."""
        return await self.tap_by_text(text, pause=0.5)

    async def get_visible_texts(self) -> list[tuple[str, int, int]]:
        """
        Извлечь видимые текстовые элементы через find_elements (LambdaTest-safe).
        НЕ используем page_source (HANG на Node 16 / sharp bug).
        Возвращает список (text, center_x, center_y).
        """
        from appium.webdriver.common.appiumby import AppiumBy

        try:
            # Метод 1: find_elements с UiSelector (работает на LambdaTest)
            def _find_texts():
                results = []
                # Ищем все TextView и Button с текстом
                for cls in ["android.widget.TextView", "android.widget.Button",
                            "android.widget.CheckedTextView", "android.widget.ImageView"]:
                    try:
                        elements = self.driver.find_elements(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            f'new UiSelector().className("{cls}")'
                        )
                        for el in elements:
                            try:
                                text = el.text or ""
                                if text.strip():
                                    loc = el.location
                                    size = el.size
                                    cx = loc['x'] + size['width'] // 2
                                    cy = loc['y'] + size['height'] // 2
                                    results.append((text.strip(), cx, cy))
                            except Exception:
                                continue
                    except Exception:
                        continue
                return results

            result = await self._run(_find_texts, timeout=15)
            if result:
                return result

        except Exception as e:
            logger.debug(f"get_visible_texts (find_elements) failed: {e}")

        if getattr(config, "DEVICE_FARM", "local") == "lambdatest":
            logger.debug("get_visible_texts: skipping page_source fallback on LambdaTest")
            return []

        # Fallback: page_source for farms where it is usable.
        try:
            source = await self._run(lambda: self.driver.page_source, timeout=8)
            if source:
                import re
                results = []
                node_pattern = re.compile(r'<node\s[^>]*>', re.DOTALL)
                text_pattern = re.compile(r'text="([^"]*)"')
                bounds_pattern = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
                for m in node_pattern.finditer(source):
                    node = m.group(0)
                    bm = bounds_pattern.search(node)
                    if not bm:
                        continue
                    tm = text_pattern.search(node)
                    text = tm.group(1).strip() if tm else ""
                    if text:
                        x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
                        results.append((text, (x1 + x2) // 2, (y1 + y2) // 2))
                return results
        except Exception as e:
            logger.debug(f"get_visible_texts (page_source fallback) failed: {e}")

        return []

    async def tap_by_visible_text_contains(
        self, keyword: str, pause: float = 1.5
    ) -> bool:
        """
        Ищет в page_source элемент, чей текст содержит keyword, и тапает по bounds-центру.
        Надёжнее tap_by_text_contains — работает на любом устройстве.
        """
        texts = await self.get_visible_texts()
        kw = keyword.lower()
        for text, cx, cy in texts:
            if kw in text.lower():
                logger.info(f"TAP BY VISIBLE TEXT CONTAINS '{keyword}': '{text}' @ ({cx},{cy})")
                await self.tap(cx, cy, pause=pause)
                return True
        logger.debug(f"tap_by_visible_text_contains: '{keyword}' not found in page_source")
        return False

    # ══════════════════════════════════════════
    # Информация об устройстве
    # ══════════════════════════════════════════

    async def get_current_activity(self) -> str:
        # current_activity HANGS on LambdaTest Node 16 (triggers sharp module)
        # Return empty string — callers must not rely on this for LT
        return ""

    async def get_current_package(self) -> str:
        result = await self._run(lambda: self.driver.current_package, timeout=10)
        return result or ""

    async def is_screen_on(self) -> bool:
        return True  # реальные устройства BrowserStack всегда включены

    async def wake_up(self):
        # LambdaTest/BrowserStack real devices are always awake after session creation
        # press_keycode(WAKEUP) triggers sharp module error on LT Node 16 — skip it
        logger.debug("wake_up: skipping (real device always active)")
        await asyncio.sleep(0.2)

    async def get_screen_resolution(self) -> tuple[int, int]:
        size = await self._run(lambda: self.driver.get_window_size(), timeout=10)
        if size:
            return size.get("width", config.SCREEN_WIDTH), size.get("height", config.SCREEN_HEIGHT)
        return config.SCREEN_WIDTH, config.SCREEN_HEIGHT

    async def get_device_info(self) -> dict:
        try:
            caps = await self._run(lambda: self.driver.capabilities, timeout=10)
            caps = caps or {}
            return {
                "model": caps.get("deviceName", config.BROWSERSTACK_DEVICE),
                "android_version": caps.get("platformVersion", config.BROWSERSTACK_OS_VERSION),
                "sdk_version": "",
                "serial": self.driver.session_id,
            }
        except Exception:
            return {
                "model": config.BROWSERSTACK_DEVICE,
                "android_version": config.BROWSERSTACK_OS_VERSION,
                "sdk_version": "",
                "serial": "bs-session",
            }

    async def wait_for_app(self, package: str, timeout: int = 30) -> bool:
        elapsed = 0
        while elapsed < timeout:
            current = await self.get_current_package()
            if package in current:
                return True
            await asyncio.sleep(1)
            elapsed += 1
        return False

    # ══════════════════════════════════════════
    # Совместимость: сценарии вызывают _run_adb напрямую
    # ══════════════════════════════════════════

    @staticmethod
    def _adb_input_text_arg(text: str) -> str:
        """Escape text for `adb shell input text`.

        Android's input command uses `%s` for spaces and the shell treats a few
        punctuation chars specially. This is intentionally conservative; it is
        enough for names/usernames and safer for generated passwords.
        """
        replacements = {
            " ": "%s",
            "&": r"\&",
            "|": r"\|",
            "<": r"\<",
            ">": r"\>",
            "(": r"\(",
            ")": r"\)",
            ";": r"\;",
            "*": r"\*",
            "'": r"\'",
            '"': r'\"',
            "`": r"\`",
            "\\": r"\\\\",
            "!": r"\!",
            "$": r"\$",
        }
        return "".join(replacements.get(ch, ch) for ch in str(text))

    async def _run_adb(self, *args, timeout: int = None) -> str:
        """
        Compat-прокси для сценариев написанных под ActionEngine.
        'shell ...' → mobile:shell; остальные команды (forward, connect) — subprocess adb.
        """
        args_list = list(args)
        if not args_list:
            return ""
        import subprocess
        adb_path = os.getenv("ADB_PATH", "/Users/flyoz/Library/Android/sdk/platform-tools/adb")

        # Local emulator: use host adb directly for *all* commands, including shell.
        # Appium mobile:shell wraps the same command but has been observed to kill
        # `uiautomator dump` with exit 137 on the local API 36 emulator.
        if getattr(config, "DEVICE_FARM", "").strip().lower() == "local":
            device = getattr(config, "LOCAL_DEVICE", "") or os.getenv("LOCAL_DEVICE", "")
            cmd = [adb_path]
            if device:
                cmd += ["-s", device]
            cmd += [str(a) for a in args_list]
        elif args_list[0] == "shell":
            command = " ".join(str(a) for a in args_list[1:])
            return await self._mshell(command, timeout=timeout or 10)
        else:
            # For non-shell ADB commands (forward, forward --remove, etc.), use subprocess
            cmd = [adb_path] + [str(a) for a in args_list]
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or 30
            )
            result = stdout.decode().strip()
            if proc.returncode != 0:
                logger.warning(f"ADB command failed: {' '.join(str(a) for a in args_list)} -> {stderr.decode().strip()}")
            return result
        except Exception as e:
            logger.warning(f"ADB subprocess error: {e}")
            return ""

    async def _run_adb_raw(self, *args, timeout: int = None) -> bytes:
        """Compat-прокси для raw ADB (exec-out screencap). Возвращает PNG через Appium."""
        args_list = list(args)
        # exec-out screencap -p — это скриншот
        if "screencap" in args_list:
            return await self.screenshot()
        return b""

    # ══════════════════════════════════════════
    # Стабы для Genymotion-specific методов
    # ══════════════════════════════════════════

    async def adb_shell_sh(self, script: str, timeout: int = 120):
        out = await self._mshell(script, timeout=timeout)
        return 0, out, ""

    async def push_local_file(
        self, local_path: str, remote_path: str, timeout: int = 600
    ) -> bool:
        logger.warning("push_local_file: не поддерживается в BrowserStack режиме")
        return False

    async def has_genymotion_flash_archive(self) -> bool:
        return False

    async def adb_root(self) -> str:
        return ""

    async def adb_reboot(self):
        logger.warning("adb_reboot: не поддерживается в BrowserStack режиме")

    async def try_flash_genymotion_gapps_zip(self, host_zip: str):
        return False, "Not supported in BrowserStack mode"

    def _save_trace_screenshot(self, png_bytes: bytes):
        try:
            filename = f"screen_{self._screenshot_counter:05d}.png"
            path = os.path.join(self.trace_dir, "screenshots", filename)
            with open(path, "wb") as f:
                f.write(png_bytes)
        except Exception as e:
            logger.debug(f"Failed to save trace screenshot: {e}")

    def _update_screen_size_from_png(self, png_bytes: bytes):
        if not png_bytes or len(png_bytes) <= 24 or png_bytes[:8] != b"\x89PNG\r\n\x1a\n":
            return
        try:
            import struct

            self._real_screen_w = struct.unpack(">I", png_bytes[16:20])[0]
            self._real_screen_h = struct.unpack(">I", png_bytes[20:24])[0]
        except Exception:
            pass
