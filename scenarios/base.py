"""
Базовый класс для всех сценариев.
Реализует универсальные методы через UIAutomator2 (без скриншотов/CV).
Все сценарии наследуются от BaseScenario.
"""
import asyncio
import re
from abc import ABC, abstractmethod
from typing import Optional

from loguru import logger

import config


class BaseScenario(ABC):
    """
    Базовый класс сценария автоматизации.
    Использует UIAutomator2 (find_element/tap_by_text/page_source) — без CV и скриншотов.
    """

    NAME = "base"

    def __init__(self, cv, action):
        # cv сохраняем для совместимости сигнатур, но НЕ используем
        self.cv = cv
        self.action = action
        self._step_count = 0

    def _log_step(self, message: str):
        """Логирование шага с номером."""
        self._step_count += 1
        logger.info(f"[{self.NAME} step {self._step_count}] {message}")

    async def _dump_screen_debug(self, label: str = ""):
        """Дамп видимых текстов для отладки (LambdaTest-safe, без page_source)."""
        try:
            pkg = await self.action.get_current_package() or "?"
            texts = await self.action.get_visible_texts()
            text_list = [t for t, _, _ in texts[:20]]
            logger.info(f"[DEBUG SCREEN {label}] pkg={pkg}, texts={text_list}")
        except Exception as e:
            logger.debug(f"_dump_screen_debug failed: {e}")

    # ═══════════════════════════════════════════════════════════════
    # ADB-based UI interaction — работает даже когда Appium UIAutomator2 сломан
    # ═══════════════════════════════════════════════════════════════

    async def _dump_ui_xml_adb(self) -> str:
        """Dump UI XML via adb shell uiautomator dump (не через Appium).

        Do not read /sdcard/ui_dump.xml when dump did not clearly succeed: on
        local Android GMS the dump command can fail without raising while an old
        file remains on device, and reading it causes stale taps on prior pages.
        """
        try:
            dump_out = await self.action._run_adb(
                "shell", "uiautomator", "dump", "/sdcard/ui_dump.xml", timeout=10
            ) or ""
            if "UI hierarchy dumped" not in dump_out:
                logger.debug(f"_dump_ui_xml_adb did not confirm fresh dump: {dump_out[:120]}")
                return ""
            xml = await self.action._run_adb(
                "shell", "cat", "/sdcard/ui_dump.xml", timeout=10
            ) or ""
            return xml
        except Exception as e:
            logger.debug(f"_dump_ui_xml_adb failed: {e}")
            return ""

    async def _find_text_in_xml(self, xml: str, keyword: str) -> tuple | None:
        """Найти текст в UI XML, вернуть (cx, cy) или None."""
        import re
        if not xml:
            return None
        kw = keyword.lower()
        # Ищем node с text или content-desc содержащим keyword
        node_pattern = re.compile(r'<node\s[^>]*>', re.DOTALL)
        bounds_pattern = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        text_pattern = re.compile(r'text="([^"]*)"')
        desc_pattern = re.compile(r'content-desc="([^"]*)"')
        for m in node_pattern.finditer(xml):
            node = m.group(0)
            tm = text_pattern.search(node)
            dm = desc_pattern.search(node)
            text = (tm.group(1) if tm else "") or (dm.group(1) if dm else "")
            if kw in text.lower():
                bm = bounds_pattern.search(node)
                if bm:
                    x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
                    return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    async def _tap_text_adb(self, keyword: str, pause: float = 1.5) -> bool:
        """Найти текст через ADB UI dump и тапнуть через adb input tap."""
        xml = await self._dump_ui_xml_adb()
        pos = await self._find_text_in_xml(xml, keyword)
        if pos:
            cx, cy = pos
            logger.info(f"[ADB TAP] '{keyword}' @ ({cx},{cy})")
            await self.action._run_adb(
                "shell", "input", "tap", str(cx), str(cy), timeout=5
            )
            await asyncio.sleep(pause)
            return True
        logger.debug(f"[ADB TAP] '{keyword}' not found in UI dump")
        return False

    async def _tap_text_contains_adb(self, keyword: str, pause: float = 1.5) -> bool:
        """Найти текст (substring match) через ADB UI dump и тапнуть."""
        return await self._tap_text_adb(keyword, pause)

    async def _find_edittext_adb(self) -> tuple | None:
        """Найти EditText в UI dump через ADB, вернуть (cx, cy)."""
        import re
        xml = await self._dump_ui_xml_adb()
        if not xml:
            return None
        node_pattern = re.compile(r'<node\s[^>]*>', re.DOTALL)
        bounds_pattern = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        class_pattern = re.compile(r'class="([^"]*)"')
        for m in node_pattern.finditer(xml):
            node = m.group(0)
            cm = class_pattern.search(node)
            cls = cm.group(1) if cm else ""
            if "EditText" in cls:
                bm = bounds_pattern.search(node)
                if bm:
                    x1, y1, x2, y2 = int(bm.group(1)), int(bm.group(2)), int(bm.group(3)), int(bm.group(4))
                    return ((x1 + x2) // 2, (y1 + y2) // 2)
        return None

    # ═══════════════════════════════════════════════════════════════
    # Универсальные wrapper-методы: ADB first → Appium fallback
    # Используйте ВМЕСТО self.action.tap_by_text / get_visible_texts
    # ═══════════════════════════════════════════════════════════════

    async def tap_text(self, keyword: str, pause: float = 1.5) -> bool:
        """Тап по тексту: ADB first, Appium fallback."""
        if await self._tap_text_adb(keyword, pause):
            return True
        if getattr(config, "DEVICE_FARM", "local") == "local":
            # Local UiAutomator2 commonly crashes in this flow; do not spend
            # minutes in Appium findElement fallback after ADB dump misses.
            return False
        try:
            return await self.action.tap_by_text(keyword, pause=pause)
        except Exception:
            return False

    async def tap_text_contains(self, keyword: str, pause: float = 1.5) -> bool:
        """Тап по тексту (substring): ADB first, Appium fallback."""
        if await self._tap_text_adb(keyword, pause):
            return True
        if getattr(config, "DEVICE_FARM", "local") == "local":
            return False
        try:
            return await self.action.tap_by_text_contains(keyword, pause=pause)
        except Exception:
            return False

    async def get_texts(self) -> list[tuple[str, int, int]]:
        """Получить видимые тексты: ADB first, Appium fallback.

        Appium UIAutomator2 на device farms иногда возвращает пустой XML/NoSuchElement,
        а `adb shell uiautomator dump` всё ещё работает. Поэтому этот общий helper не
        должен напрямую полагаться только на `action.get_visible_texts()`.
        """
        xml = await self._dump_ui_xml_adb()
        if xml and len(xml) > 100:
            results: list[tuple[str, int, int]] = []
            node_pattern = re.compile(r'<node\s[^>]*>', re.DOTALL)
            bounds_pattern = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
            text_pattern = re.compile(r'text="([^"]*)"')
            desc_pattern = re.compile(r'content-desc="([^"]*)"')
            for m in node_pattern.finditer(xml):
                node = m.group(0)
                bm = bounds_pattern.search(node)
                if not bm:
                    continue
                tm = text_pattern.search(node)
                dm = desc_pattern.search(node)
                text = ((tm.group(1) if tm else "") or (dm.group(1) if dm else "")).strip()
                if text:
                    x1, y1, x2, y2 = map(int, bm.groups())
                    results.append((text, (x1 + x2) // 2, (y1 + y2) // 2))
            if results:
                return results
        if getattr(config, "DEVICE_FARM", "local") == "local":
            return []
        try:
            return await self.action.get_visible_texts()
        except Exception as e:
            logger.debug(f"get_texts failed: {e}")
            return []

    async def dismiss_setup_wizard(self):
        """Пропуск initial setup wizard (OOBE) на новом устройстве."""
        self._log_step("Checking for setup wizard / OOBE")
        action = self.action

        # Сначала: разбудить экран и закрыть все оверлеи
        try:
            await action.press_key("KEYCODE_WAKEUP")
            await asyncio.sleep(1)
            await action.press_key("KEYCODE_MENU")
            await asyncio.sleep(0.5)
            # Свайп вверх чтобы разблокировать если locked
            await action.swipe(540, 1800, 540, 600, duration=300)
            await asyncio.sleep(1)
        except Exception:
            pass

        for attempt in range(15):
            pkg = (await self.action.get_current_package() or "").lower()

            # Если уже на обычном приложении/launcher/settings — OOBE закончен.
            # Play Store/Chrome are valid post-setup apps too; do not spend minutes
            # trying to dismiss setup wizard while a normal app is open.
            if any(p in pkg for p in ("launcher", "settings", "gms", "vending", "chrome")):
                if "provision" not in pkg and "setupwizard" not in pkg:
                    if attempt > 0:
                        logger.info(f"Setup wizard dismissed after {attempt} attempts")
                    return

            # Типичные кнопки OOBE
            dismissed = False
            for btn in [
                "Accept", "I agree", "Agree", "Next", "Continue",
                "Skip", "No thanks", "Not now", "Allow", "DONE",
                "Set up", "START", "Start", "OK", "Got it",
            ]:
                if await self.tap_text(btn, pause=1.0):
                    dismissed = True
                    break
                if await self.tap_text_contains(btn, pause=1.0):
                    dismissed = True
                    break

            if not dismissed:
                # Пробуем press_back для диалогов
                await self.action.press_back()
                await asyncio.sleep(1.0)

            await asyncio.sleep(1.5)

        logger.warning("dismiss_setup_wizard: max attempts reached")

    @abstractmethod
    async def run(self):
        """Главный метод — выполнить весь сценарий."""
        pass

    # ══════════════════════════════════════════
    # UIAutomator2-методы (замена CV)
    # ══════════════════════════════════════════

    async def tap_text(self, text: str, pause: float = 1.5) -> bool:
        """Тап по точному тексту: ADB first, Appium fallback."""
        ok = await self._tap_text_adb(text, pause=pause)
        if not ok and getattr(config, "DEVICE_FARM", "local") != "local":
            ok = await self.action.tap_by_text(text, pause=pause)
        if ok:
            self._log_step(f"TAP TEXT: '{text}'")
        return ok

    async def tap_text_contains(self, text: str, pause: float = 1.5) -> bool:
        """Тап по подстроке текста: ADB first, Appium fallback."""
        ok = await self._tap_text_contains_adb(text, pause=pause)
        if not ok and getattr(config, "DEVICE_FARM", "local") != "local":
            ok = await self.action.tap_by_text_contains(text, pause=pause)
        if ok:
            self._log_step(f"TAP TEXT CONTAINS: '{text}'")
        return ok

    async def tap_text_scroll(self, text: str, pause: float = 1.5) -> bool:
        """Скролл + тап по тексту: ADB first, Appium fallback."""
        ok = False
        for _ in range(6):
            ok = await self._tap_text_contains_adb(text, pause=pause)
            if ok:
                break
            try:
                await self.action._run_adb("shell", "input", "swipe", "540", "1900", "540", "650", "350", timeout=5)
                await asyncio.sleep(0.7)
            except Exception:
                break
        if not ok and getattr(config, "DEVICE_FARM", "local") != "local":
            ok = await self.action.tap_by_text_scroll(text, pause=pause)
        if ok:
            self._log_step(f"TAP TEXT SCROLL: '{text}'")
        return ok

    async def tap_any(self, texts: list[str], pause: float = 1.5) -> str | None:
        """Пробует тапнуть первый найденный текст из списка. Возвращает найденный текст или None."""
        for text in texts:
            if await self.tap_text(text, pause=pause):
                self._log_step(f"TAP ANY: found '{text}'")
                return text
        return None

    async def tap_any_contains(self, texts: list[str], pause: float = 1.5) -> str | None:
        """Пробует тапнуть первый найденный substring из списка. Возвращает найденный или None."""
        for text in texts:
            if await self.tap_text_contains(text, pause=pause):
                self._log_step(f"TAP ANY CONTAINS: found '{text}'")
                return text
        return None

    async def type_into_field(
        self,
        field_text: str,
        value: str,
        clear_first: bool = True,
        press_enter: bool = False,
        pause: float = 0.5,
    ) -> bool:
        """
        Найти поле по тексту метки/подсказки → тапнуть → ввести текст.
        field_text: текст label/hint для поиска через UIAutomator2.
        """
        found = await self.tap_text_contains(field_text, pause=0.5)
        if not found:
            # Пробуем через EditText с hint
            found = await self._tap_edittext_by_hint(field_text)
        if not found:
            self._log_step(f"type_into_field: field '{field_text}' not found")
            return False

        if clear_first:
            await self.action.clear_field()
            await asyncio.sleep(0.2)

        await self.action.type_text(value)
        await asyncio.sleep(pause)

        if press_enter:
            await self.action.press_enter()
            await asyncio.sleep(0.5)

        return True

    async def _tap_edittext_by_hint(self, hint: str) -> bool:
        """Найти EditText с hint через UIAutomator2 и тапнуть. Работает с обоими engine."""
        import re

        # Путь 1: Appium driver (если доступен). Skip on local: UiAutomator2
        # is unstable/crashes in the Google WebView signup flow.
        if hasattr(self.action, 'driver') and getattr(config, "DEVICE_FARM", "local") != "local":
            try:
                from appium.webdriver.common.appiumby import AppiumBy
                def _find():
                    selector = f'new UiSelector().className("android.widget.EditText").textContains("{hint}")'
                    el = self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, selector)
                    el.click()
                    return True
                result = await self.action._run(_find, timeout=8)
                if result:
                    return True
            except Exception:
                pass

        # Путь 2: ADB uiautomator dump (для ActionEngine / Genymotion)
        try:
            xml = await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
            hint_lower = hint.lower()
            for node in re.finditer(r'<node\b[^>]*?/?>', xml):
                node_str = node.group(0)
                if 'class="android.widget.EditText"' not in node_str:
                    continue
                text_match = re.search(r'text="([^"]*)"', node_str)
                desc_match = re.search(r'content-desc="([^"]*)"', node_str)
                node_text = (text_match.group(1) if text_match else "")
                node_desc = (desc_match.group(1) if desc_match else "")
                if hint_lower in node_text.lower() or hint_lower in node_desc.lower():
                    m = bounds_re.search(node_str)
                    if m:
                        x = (int(m.group(1)) + int(m.group(3))) // 2
                        y = (int(m.group(2)) + int(m.group(4))) // 2
                        logger.info(f"_tap_edittext_by_hint('{hint}') ADB at ({x}, {y})")
                        await self.action._run_adb("shell", "input", "tap", str(x), str(y), timeout=5)
                        return True
        except Exception as e:
            logger.debug(f"_tap_edittext_by_hint ADB fallback failed: {e}")

        return False

    async def _find_and_click_any_edittext(
        self, hints: list[str] = None, focused: bool = False
    ) -> bool:
        """Найти и кликнуть любой EditText. Работает с обоими engine (Appium + ADB).

        Ищет по hints (textContains), затем по focused, затем первый EditText.
        Заменяет все closure-паттерны с self.action.driver.
        """
        import re

        # === Путь 1: Appium driver (если доступен). Skip on local: UiAutomator2
        # is unstable/crashes in the Google WebView signup flow. ===
        if hasattr(self.action, 'driver') and getattr(config, "DEVICE_FARM", "local") != "local":
            try:
                from appium.webdriver.common.appiumby import AppiumBy
                def _find():
                    if hints:
                        for hint in hints:
                            sel = f'new UiSelector().className("android.widget.EditText").textContains("{hint}")'
                            try:
                                el = self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                                el.click()
                                return True
                            except Exception:
                                continue
                    if focused:
                        sel = 'new UiSelector().className("android.widget.EditText").focused(true)'
                        try:
                            el = self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                            el.click()
                            return True
                        except Exception:
                            pass
                    # Последний шанс — любой EditText
                    for cls in ("android.widget.EditText", "android.widget.AutoCompleteTextView"):
                        sel = f'new UiSelector().className("{cls}")'
                        try:
                            el = self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                            el.click()
                            return True
                        except Exception:
                            continue
                    return False
                result = await self.action._run(_find, timeout=10)
                if result:
                    return True
            except Exception:
                pass

        # === Путь 2: ADB uiautomator dump (Genymotion) ===
        try:
            await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
            xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
            bounds_re = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')

            def _tap_first_edittext(match_hints=None, match_focused=False):
                """Поиск EditText по критериям. Возвращает (x, y) или None."""
                for node in re.finditer(r'<node\b[^>]*?/?>', xml):
                    ns = node.group(0)
                    if 'class="android.widget.EditText"' not in ns and \
                       'class="android.widget.AutoCompleteTextView"' not in ns:
                        continue
                    if match_hints:
                        text_m = re.search(r'text="([^"]*)"', ns)
                        desc_m = re.search(r'content-desc="([^"]*)"', ns)
                        nt = (text_m.group(1).lower() if text_m else "")
                        nd = (desc_m.group(1).lower() if desc_m else "")
                        if not any(h.lower() in nt or h.lower() in nd for h in match_hints):
                            continue
                    m = bounds_re.search(ns)
                    if m:
                        return ((int(m.group(1)) + int(m.group(3))) // 2,
                                (int(m.group(2)) + int(m.group(4))) // 2)
                return None

            # Ищем по hints
            pos = _tap_first_edittext(match_hints=hints) if hints else None
            # Focused
            if not pos and focused:
                pos = _tap_first_edittext()
            # Первый EditText
            if not pos:
                pos = _tap_first_edittext()

            if pos:
                await self.action._run_adb("shell", "input", "tap", str(pos[0]), str(pos[1]), timeout=5)
                return True
        except Exception as e:
            logger.debug(f"_find_and_click_any_edittext ADB failed: {e}")

        return False

    async def type_into_active_field(self, value: str, clear_first: bool = True) -> bool:
        """Ввести текст в активное (focused) поле."""
        if clear_first:
            await self.action.clear_field()
            await asyncio.sleep(0.2)
        await self.action.type_text(value)
        await asyncio.sleep(0.3)
        return True

    async def wait_for_text(
        self,
        text: str,
        timeout: int = 30,
        poll_interval: float = 2.0,
        exact: bool = True,
    ) -> bool:
        """
        Ждать появления текста на экране через page_source.
        Возвращает True если текст появился.
        """
        elapsed = 0.0
        while elapsed < timeout:
            texts = await self.get_texts()
            found = any(
                (text == t[0] if exact else text.lower() in t[0].lower())
                for t in texts
            )
            if found:
                logger.info(f"[{self.NAME}] Text appeared: '{text}' after {elapsed:.0f}s")
                return True
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        logger.warning(f"[{self.NAME}] Text '{text}' did not appear in {timeout}s")
        return False

    async def wait_for_any_text(
        self,
        texts: list[str],
        timeout: int = 30,
        poll_interval: float = 2.0,
    ) -> str | None:
        """
        Ждать появления любого из текстов.
        Возвращает первый найденный текст или None.
        """
        elapsed = 0.0
        while elapsed < timeout:
            visible = await self.get_texts()
            visible_strs = [t[0].lower() for t in visible]
            for text in texts:
                if any(text.lower() in v for v in visible_strs):
                    logger.info(f"[{self.NAME}] Found text: '{text}' after {elapsed:.0f}s")
                    return text
            await asyncio.sleep(poll_interval)
            elapsed += poll_interval
        logger.warning(f"[{self.NAME}] None of {texts} appeared in {timeout}s")
        return None

    async def get_visible_text_list(self) -> list[str]:
        """Возвращает список всех видимых текстов на экране."""
        items = await self.get_texts()
        return [t[0] for t in items]

    async def is_text_visible(self, text: str, exact: bool = False) -> bool:
        """Проверить есть ли текст на экране прямо сейчас."""
        texts = await self.get_texts()
        for t, _, _ in texts:
            if exact:
                if t == text:
                    return True
            else:
                if text.lower() in t.lower():
                    return True
        return False

    async def dismiss_popups(self, max_attempts: int = 3):
        """Попробовать закрыть попапы через стандартные кнопки."""
        dismiss_labels = [
            "No thanks", "Not now", "Skip", "Later", "Cancel",
            "OK", "Got it", "Allow", "Accept", "Dismiss",
        ]
        for i in range(max_attempts):
            found = await self.tap_any(dismiss_labels, pause=1.0)
            if not found:
                break
            logger.info(f"[{self.NAME}] Dismissed popup #{i + 1}: '{found}'")

    async def handle_unexpected_popup(self) -> bool:
        """
        Обработать неожиданный попап/диалог через UIAutomator2.
        Возвращает True если попап был закрыт.
        """
        dismiss_labels = [
            "No thanks", "Not now", "Skip", "Later",
            "OK", "Got it", "Allow", "Accept", "Dismiss", "Cancel",
        ]
        found = await self.tap_any(dismiss_labels, pause=1.0)
        return found is not None

    async def save_debug_screenshot(self, prefix: str = "debug"):
        """Заглушка — скриншоты отключены (LambdaTest Node16 sharp bug)."""
        logger.debug(f"[{self.NAME}] save_debug_screenshot('{prefix}') — skipped (no screenshots)")
        return ""

    # ══════════════════════════════════════════
    # CV-замены: UIAutomator2-based методы
    # ══════════════════════════════════════════

    async def find_and_tap(
        self,
        description: str,
        retries: int = 3,
        pause_after: float = 1.5,
        confidence_threshold: float = 0.0,
        timeout: int = 10,
    ) -> bool:
        """
        Найти элемент по текстовому описанию через UIAutomator2 page_source и тапнуть.
        Заменяет CV-based find_and_tap.

        Извлекает ключевые слова из description и ищет их в page_source.
        """
        keywords = self._extract_keywords_from_description(description)
        for attempt in range(retries):
            for kw in keywords:
                # Пробуем ADB-first exact match
                if await self.tap_text(kw, pause=pause_after):
                    self._log_step(f"find_and_tap: matched '{kw}' from '{description[:50]}'")
                    return True

            # Пробуем ADB-first contains
            for kw in keywords:
                if await self.tap_text_contains(kw, pause=pause_after):
                    self._log_step(f"find_and_tap: contains '{kw}' from '{description[:50]}'")
                    return True

            # Пробуем UI dump/page_source search (с координатами)
            texts = await self.get_texts()
            desc_lower = description.lower()
            for text, cx, cy in texts:
                text_lower = text.lower()
                # Проверяем совпадение по ключевым словам
                for kw in keywords:
                    if kw.lower() in text_lower:
                        self._log_step(f"find_and_tap: page_source '{text}' @ ({cx},{cy})")
                        await self.action.tap(cx, cy, pause=pause_after)
                        return True

            # Пробуем scroll + search
            for kw in keywords:
                if await self.tap_text_scroll(kw, pause=pause_after):
                    self._log_step(f"find_and_tap: scroll+contains '{kw}'")
                    return True

            if attempt < retries - 1:
                await asyncio.sleep(1.0)

        logger.debug(f"find_and_tap: NOT FOUND '{description[:60]}' after {retries} retries")
        return False

    async def find_and_type(
        self,
        description: str,
        value: str,
        clear_first: bool = True,
        retries: int = 3,
        press_enter: bool = False,
    ) -> bool:
        """
        Найти поле ввода по описанию и ввести текст.
        Заменяет CV-based find_and_type.

        Стратегия:
        1. Ищем EditText/input поля через UIAutomator2
        2. Ищем по тексту label/hint рядом с полем
        3. Ищем по ключевым словам из description
        """
        keywords = self._extract_keywords_from_description(description)

        for attempt in range(retries):
            # Стратегия 1: найти EditText по hint/placeholder тексту
            for kw in keywords:
                found = await self._tap_edittext_by_hint(kw)
                if found:
                    await asyncio.sleep(0.3)
                    if clear_first:
                        await self.action.clear_field()
                        await asyncio.sleep(0.1)
                    await self.action.type_text(value)
                    self._log_step(f"find_and_type: via EditText hint '{kw}'")
                    if press_enter:
                        await self.action.press_enter()
                    return True

            # Стратегия 2: найти по тексту label → тапнуть → поле рядом
            for kw in keywords:
                if await self.tap_text_contains(kw, pause=0.5):
                    await asyncio.sleep(0.3)
                    # После тапа по label фокус может быть на поле
                    if clear_first:
                        await self.action.clear_field()
                        await asyncio.sleep(0.1)
                    await self.action.type_text(value)
                    self._log_step(f"find_and_type: via label tap '{kw}'")
                    if press_enter:
                        await self.action.press_enter()
                    return True

            # Стратегия 3: найти первый EditText на странице (engine-agnostic)
            found = False

            # Путь A: Appium driver (если доступен). Skip on local: UiAutomator2
            # is unstable/crashes in Google signup WebView; host ADB is safer.
            if hasattr(self.action, 'driver') and getattr(config, "DEVICE_FARM", "local") != "local":
                try:
                    from appium.webdriver.common.appiumby import AppiumBy
                    def _find_any_edittext():
                        selectors = [
                            'new UiSelector().className("android.widget.EditText").focused(true)',
                            'new UiSelector().className("android.widget.EditText")',
                            'new UiSelector().className("android.widget.AutoCompleteTextView")',
                        ]
                        for sel in selectors:
                            try:
                                el = self.action.driver.find_element(AppiumBy.ANDROID_UIAUTOMATOR, sel)
                                el.click()
                                return True
                            except Exception:
                                continue
                        return False
                    found = await self.action._run(_find_any_edittext, timeout=8)
                except Exception:
                    pass

            # Путь B: ADB uiautomator dump (local and non-driver engines)
            if not found:
                try:
                    import re as _re
                    await self.action._run_adb("shell", "uiautomator", "dump", "/sdcard/uidump.xml", timeout=15)
                    _xml = await self.action._run_adb("shell", "cat", "/sdcard/uidump.xml", timeout=10) or ""
                    bounds_re = _re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
                    for _node in _re.finditer(r'<node\b[^>]*?/?>', _xml):
                        _ns = _node.group(0)
                        if 'class="android.widget.EditText"' in _ns or 'class="android.widget.AutoCompleteTextView"' in _ns:
                            _m = bounds_re.search(_ns)
                            if _m:
                                _x = (int(_m.group(1)) + int(_m.group(3))) // 2
                                _y = (int(_m.group(2)) + int(_m.group(4))) // 2
                                await self.action._run_adb("shell", "input", "tap", str(_x), str(_y), timeout=5)
                                found = True
                                break
                except Exception:
                    pass
            if found:
                await asyncio.sleep(0.3)
                if clear_first:
                    await self.action.clear_field()
                    await asyncio.sleep(0.1)
                await self.action.type_text(value)
                self._log_step(f"find_and_type: via focused EditText")
                if press_enter:
                    await self.action.press_enter()
                return True

            # Стратегия 4: scroll ищем поле
            for kw in keywords:
                found = await self._tap_edittext_by_hint(kw)
                if found:
                    await asyncio.sleep(0.3)
                    if clear_first:
                        await self.action.clear_field()
                        await asyncio.sleep(0.1)
                    await self.action.type_text(value)
                    self._log_step(f"find_and_type: via scroll EditText '{kw}'")
                    if press_enter:
                        await self.action.press_enter()
                    return True

            if attempt < retries - 1:
                await asyncio.sleep(1.0)

        logger.debug(f"find_and_type: NOT FOUND field for '{description[:60]}' after {retries} retries")
        return False

    async def get_screen_state(self) -> str:
        """
        Определить текущий экран через page_source UIAutomator2.
        Заменяет CV-based get_screen_state.
        """
        try:
            texts = await self.action.get_visible_texts()
            text_set = {t.lower() for t, _, _ in texts}
            all_text = " ".join(t.lower() for t, _, _ in texts)
            pkg = (await self.action.get_current_package() or "").lower()

            # Play Store screens
            if "com.android.vending" in pkg:
                if any(kw in all_text for kw in ("sign in", "sign-in", "signin")):
                    return "play_store_signin"
                if any(kw in all_text for kw in ("install", "open", "update")):
                    return "play_store_app_page"
                if any(kw in all_text for kw in ("apps", "games", "search")):
                    return "play_store_main"
                return "play_store"

            # Settings screens
            if "com.android.settings" in pkg:
                if any(kw in all_text for kw in ("add account", "account type", "google")):
                    return "settings_add_account"
                if any(kw in all_text for kw in ("passwords", "accounts", "passkeys")):
                    return "settings_accounts"
                return "settings"

            # Google sign-in
            if "com.google.android.gms" in pkg or "com.google.android.gsf" in pkg:
                if any(kw in all_text for kw in ("sign in", "email", "phone", "password")):
                    return "google_login"
                if any(kw in all_text for kw in ("create account", "first name", "last name")):
                    return "google_register"
                if any(kw in all_text for kw in ("verification", "code", "verify")):
                    return "google_verify"
                return "google_gms"

            # Google Chrome
            if "com.android.chrome" in pkg:
                if "accounts.google.com" in all_text or "create" in all_text:
                    return "chrome_google_signup"
                return "chrome"

            # Clash Royale
            if "com.supercell.clashroyale" in pkg:
                if any(kw in all_text for kw in ("tutorial", "drag", "play")):
                    return "game_tutorial"
                if any(kw in all_text for kw in ("shop", "store", "buy")):
                    return "game_shop"
                if any(kw in all_text for kw in ("menu", "battle", "clan")):
                    return "game_main_menu"
                return "game"

            # Launcher
            if "launcher" in pkg:
                return "home_screen"

            return f"unknown:{pkg}"

        except Exception as e:
            logger.debug(f"get_screen_state failed: {e}")
            return "error"

    async def detect_stage_from_page_source(self) -> str:
        """
        Определить стадию регистрации/входа через page_source.
        Заменяет CV-based detect_registration_stage.
        """
        try:
            texts = await self.action.get_visible_texts()
            text_set = {t.lower() for t, _, _ in texts}
            all_text = " ".join(t.lower() for t, _, _ in texts)

            # Проверка завершения
            if any(kw in all_text for kw in ("google account", "account created", "welcome", "account added")):
                return "done"

            # Phone verification code input
            if any(kw in all_text for kw in ("verification code", "enter the code", "6-digit", "enter code")):
                return "phone_code"

            # Phone number input
            if "phone number" in all_text and "verification" not in all_text:
                return "phone_input"

            # Password
            if any(kw in all_text for kw in ("create password", "confirm password", "strong password", "retype password")):
                return "password"

            # Email / username
            if any(kw in all_text for kw in ("gmail address", "username", "email address", "create your own")):
                return "email"

            # Birthday/gender
            if any(kw in all_text for kw in ("birthday", "date of birth", "month", "year", "gender")):
                return "birthday"

            # Name
            if any(kw in all_text for kw in ("first name", "last name", "enter your name")):
                return "name"

            # Terms
            if any(kw in all_text for kw in ("privacy policy", "terms of service", "i agree", "agree and continue")):
                return "terms"

            # Extra/skip screens
            if any(kw in all_text for kw in ("skip", "not now", "later", "no thanks", "back up", "add phone")):
                return "extras"

            # Settings navigation
            pkg = (await self.action.get_current_package() or "").lower()
            if "settings" in pkg:
                return "settings"

            # Play Store sign-in
            if "com.android.vending" in pkg:
                if any(kw in all_text for kw in ("sign in", "sign-in")):
                    return "play_store_signin"
                return "play_store"

        except Exception as e:
            logger.debug(f"detect_stage_from_page_source failed: {e}")

        return "unknown"

    async def analyze_current_screen(self, context: str = "", target: str = "") -> dict:
        """
        Анализ текущего экрана через page_source UIAutomator2.
        Заменяет CV-based analyze_screen.
        Возвращает dict с keys: screen_name, description, elements, suggested_action
        """
        try:
            texts = await self.action.get_visible_texts()
            pkg = (await self.action.get_current_package() or "").lower()
            all_text = " ".join(t for t, _, _ in texts)

            # Определяем screen_name
            screen_state = await self.get_screen_state()

            # Формируем список элементов из page_source
            elements = []
            for text, cx, cy in texts:
                if not text or len(text) < 1:
                    continue
                text_lower = text.lower()
                el_type = "text"
                if any(kw in text_lower for kw in ("button", "btn", "submit", "next", "continue", "sign in",
                                                     "create", "save", "accept", "agree", "install", "open",
                                                     "buy", "cancel", "skip", "ok", "done", "confirm")):
                    el_type = "button"
                elif any(kw in text_lower for kw in ("enter", "input", "type", "search", "email", "password",
                                                       "username", "phone", "name")):
                    el_type = "input"

                elements.append({
                    "name": text[:80],
                    "x": cx,
                    "y": cy,
                    "width": 200,
                    "height": 60,
                    "element_type": el_type,
                    "text": text,
                    "confidence": 0.8 if el_type != "text" else 0.5,
                })

            description = f"Screen: {screen_state}, Package: {pkg}, {len(elements)} visible texts"

            # Suggested action based on screen state
            suggested = None
            if "phone_input" in screen_state:
                suggested = "Enter phone number"
            elif "password" in screen_state:
                suggested = "Enter password"
            elif "email" in screen_state:
                suggested = "Enter email/username"
            elif "terms" in screen_state:
                suggested = "Accept terms"

            return {
                "screen_name": screen_state,
                "description": description,
                "elements": elements,
                "suggested_action": suggested,
            }
        except Exception as e:
            logger.debug(f"analyze_current_screen failed: {e}")
            return {
                "screen_name": "error",
                "description": str(e),
                "elements": [],
                "suggested_action": None,
            }

    def _scale_cv_coord(self, x: int, y: int, real_w: int = 0, real_h: int = 0) -> tuple[int, int]:
        """
        Stub — координаты уже реальные из page_source.
        Оставлен для совместимости вызовов.
        """
        return x, y

    # ══════════════════════════════════════════
    # Утилиты
    # ══════════════════════════════════════════

    @staticmethod
    def _extract_keywords_from_description(description: str) -> list[str]:
        """
        Извлечь ключевые слова из текстового описания элемента.
        Например: "'Sign in' button in Play Store" → ["Sign in", "sign in"]
        """
        keywords = []

        # Извлекаем текст в кавычках. Если в описании явно указан UI-label
        # ('Create account', 'For myself'), используем именно эти фразы как
        # кандидаты. Раньше regex ниже дополнительно извлекал обломки вроде
        # "'Create"/"account'" и общие слова из контекста (например "sign"),
        # из-за чего find_and_tap мог повторно нажать Sign in вместо Create account.
        quoted = re.findall(r"['\"]([^'\"]+)['\"]", description)
        keywords.extend(quoted)
        if quoted:
            result = []
            for kw in keywords:
                if kw not in result:
                    result.append(kw)
                if kw.lower() not in [k.lower() for k in result]:
                    result.append(kw.lower())
            return result[:15]

        # Извлекаем значимые слова (убираем артикли, предлоги и т.д.)
        stop_words = {
            "the", "a", "an", "in", "on", "at", "to", "for", "of", "with",
            "or", "and", "is", "are", "was", "were", "be", "been", "being",
            "have", "has", "had", "do", "does", "did", "will", "would",
            "could", "should", "may", "might", "must", "shall", "can",
            "button", "field", "input", "option", "menu", "text", "item",
            "element", "row", "screen", "page", "dialog", "popup", "icon",
            "image", "link", "tab", "list", "section", "area", "corner",
            "top", "bottom", "left", "right", "center", "upper", "lower",
            "green", "blue", "red", "white", "black", "gray", "primary",
            "visible", "anywhere", "line", "three", "any", "some", "all",
            "new", "create", "click", "tap", "press", "select", "choose",
            "if", "appears", "showing", "shows", "displayed", "contains",
            "may", "need", "needs", "first", "second", "this", "that",
            "it", "its", "your", "my", "our", "their", "from", "into",
            "about", "after", "before", "between", "through", "during",
            "without", "within", "along", "following", "across", "behind",
            "beyond", "plus", "except", "up", "down", "out", "off", "over",
            "under", "again", "further", "then", "once", "here", "there",
            "when", "where", "why", "how", "what", "which", "who", "whom",
            "whose", "whether", "while", "although", "though", "even",
            "such", "both", "each", "few", "more", "most", "other", "only",
            "own", "same", "so", "than", "too", "very", "just", "because",
            "as", "until", "also", "not", "no", "nor", "yet",
            "de", "la", "le", "les", "des", "du", "un", "une",
            "кнопка", "поле", "текст", "окно", "экран", "страница",
        }

        words = re.findall(r"[A-Za-zА-Яа-я0-9']+", description)
        for word in words:
            if word.lower() not in stop_words and len(word) > 1:
                keywords.append(word)

        # Добавляем lowercase варианты
        result = []
        for kw in keywords:
            if kw not in result:
                result.append(kw)
            if kw.lower() not in [k.lower() for k in result]:
                result.append(kw.lower())

        # Добавляем составные фразы из кавычек
        for q in quoted:
            lower = q.lower()
            if lower not in [k.lower() for k in result]:
                result.append(lower)

        return result[:15]  # Не больше 15 ключевых слов

    async def _navigate_to_add_account_google(self) -> bool:
        """
        Навигация до экрана выбора типа аккаунта → тап Google.
        Делегирует в action.open_add_account_settings().
        """
        action = self.action

        # Debug: что на экране прямо сейчас?
        await self._dump_screen_debug("navigate_to_google_start")

        # ── Стратегия 1: UIAutomator tap_by_text "Add account" → "Google" ──
        added = await action.uiautomator_tap_by_text("Add account")
        if added:
            await asyncio.sleep(2.0)
            google_tapped = await action.uiautomator_tap_by_text("Google")
            if not google_tapped:
                google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
            if google_tapped:
                await asyncio.sleep(4)
                return True

        # ── Стратегия 2: page_source поиск "Add account" ──
        texts = await action.get_visible_texts()
        for text, cx, cy in texts:
            if "add account" in text.lower():
                self._log_step(f"Found 'Add account' via page_source at ({cx},{cy})")
                await action.tap(cx, cy, pause=2.0)
                await asyncio.sleep(2.0)
                google_tapped = await action.uiautomator_tap_by_text("Google")
                if not google_tapped:
                    google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
                if google_tapped:
                    await asyncio.sleep(4)
                    return True

        # ── Стратегия 3: Scroll-поиск "Passwords & accounts" ──
        for text_variant in (
            "Passwords & accounts",
            "Passwords, passkeys & accounts",
            "Passwords, passkeys, and accounts",
            "Accounts",
        ):
            found = await action.tap_by_text_scroll(text_variant, pause=2.5)
            if found:
                self._log_step(f"Found '{text_variant}' via scroll")
                await asyncio.sleep(1)
                # Теперь ищем Add account
                added = await action.uiautomator_tap_by_text("Add account")
                if added:
                    await asyncio.sleep(2.0)
                    google_tapped = await action.uiautomator_tap_by_text("Google")
                    if not google_tapped:
                        google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
                    if google_tapped:
                        await asyncio.sleep(4)
                        return True
                break

        # ── Стратегия 4: Свайп + page_source поиск ──
        self._log_step("Fallback: swipe scroll + page_source search")
        for scroll_attempt in range(8):
            if scroll_attempt > 0:
                cur_pkg = (await action.get_current_package() or "").lower()
                if "settings" not in cur_pkg:
                    break
                await action.swipe_up()
                await asyncio.sleep(1.5)

            # Пробуем Add account напрямую
            added = await action.uiautomator_tap_by_text("Add account")
            if added:
                await asyncio.sleep(2.0)
                google_tapped = await action.uiautomator_tap_by_text("Google")
                if not google_tapped:
                    google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
                if google_tapped:
                    await asyncio.sleep(4)
                    return True

            # page_source
            texts = await action.get_visible_texts()
            for text, cx, cy in texts:
                if any(kw in text.lower() for kw in ("passwords", "accounts", "passkeys")):
                    self._log_step(f"Found '{text}' via page_source @ ({cx},{cy})")
                    await action.tap(cx, cy, pause=2.5)
                    await asyncio.sleep(1)
                    added = await action.uiautomator_tap_by_text("Add account")
                    if added:
                        await asyncio.sleep(2.0)
                        google_tapped = await action.uiautomator_tap_by_text("Google")
                        if not google_tapped:
                            google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
                        if google_tapped:
                            await asyncio.sleep(4)
                            return True
                    break

        # ── Стратегия 5: Settings Search ──
        self._log_step("Trying Settings Search for 'Add account'")
        search_tapped = await action.uiautomator_tap_by_text("Search settings")
        if not search_tapped:
            search_tapped = await action.tap_by_visible_text_contains("Search settings", pause=1.5)
        if search_tapped:
            await asyncio.sleep(1.5)

            # Ищем EditText и вводим "Add account" (engine-agnostic)
            clicked = await self._find_and_click_any_edittext()
            if clicked:
                await asyncio.sleep(0.4)
                await action.clear_field()
                await action.type_text("Add account")
            await asyncio.sleep(2)

            # Тапаем первый результат
            for result_text in ("Add account", "Accounts"):
                if await action.tap_by_text_contains(result_text, pause=2.5):
                    self._log_step(f"Settings Search found: '{result_text}'")
                    await asyncio.sleep(1)
                    google_tapped = await action.uiautomator_tap_by_text("Google")
                    if not google_tapped:
                        google_tapped = await action.tap_by_text_scroll("Google", pause=2.0)
                    if google_tapped:
                        await asyncio.sleep(4)
                        return True

        logger.warning(f"[{self.NAME}] _navigate_to_add_account_google: all strategies failed")
        return False
