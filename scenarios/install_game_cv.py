"""Install the configured game from Google Play using CV autopilot."""
from __future__ import annotations

import asyncio
import os
import re

from loguru import logger

import config
from core.cv_autopilot import CVAutopilot
from core.cv_engine import CVEngine
from core.game_profiles import GameProfile
from core.cv_prompt_templates import INSTALL_GOAL_TEMPLATE, render_prompt_template
from scenarios.base import BaseScenario
from scenarios.manual_control import ManualControlScenario


class InstallGameCVScenario(BaseScenario):
    """Screenshot-driven Play Store install flow."""

    NAME = "install_game_cv"

    async def run(self) -> bool:
        logger.info("=" * 50)
        logger.info(f"SCENARIO: Install {self.game_name} (CV)")
        logger.info("=" * 50)

        if not self.package_name:
            raise RuntimeError(
                "GAME_PACKAGE is required for reliable install polling. "
                "Use GAME_PROFILE for a known game or set GAME_PACKAGE manually."
            )

        if await self.action.is_package_installed(self.package_name):
            logger.info(f"{self.game_name} already installed")
            await self._launch_game()
            return True

        self._log_step(f"Opening Play Store page for {self.game_name}")
        await self._open_play_store_page()
        unavailable_reason = await self._play_store_unavailable_reason()
        if unavailable_reason:
            apk_path = getattr(config, "GAME_APK_PATH", "")
            if apk_path:
                await self._install_from_apk(apk_path)
                await self._launch_game()
                return True
            raise RuntimeError(
                f"{unavailable_reason}. Set GAME_APK_PATH to a local APK to sideload, "
                "or use a Google Play account/region where the app is available."
            )
        if await self._tap_play_store_primary_button():
            await self._wait_until_installed(timeout=240)
            await self._launch_game()
            return True

        autopilot = CVAutopilot(
            action=self.action,
            cv=CVEngine(),
            max_steps=20,
            allow_risky_actions=False,
            stop_on_risky_action=True,
        )
        try:
            result = await autopilot.run(
                self._goal_text(),
                {
                    "app_name": self.game_name,
                    "install_query": self.profile.install_query or self.game_name,
                    "coordinate_scale": getattr(config, "CV_COORDINATE_SCALE", ""),
                    "clear_before_type": "1",
                },
            )
        except RuntimeError as e:
            if self._manual_fallback_enabled(e):
                logger.warning(f"CV install unavailable, switching to manual checkpoint: {e}")
                return await ManualControlScenario(
                    cv=None,
                    action=self.action,
                    stage_name="install",
                    hint=(
                        f"Install and launch {self.game_name} manually, then press "
                        "Continue Automation in the dashboard."
                    ),
                ).run()
            raise
        logger.info(f"CV install result: {result.status} ({result.reason})")
        if not result.ok:
            raise RuntimeError(f"CV install failed: {result.reason}")

        await self._wait_until_installed(timeout=240)
        await self._launch_game()
        return True

    @property
    def game_name(self) -> str:
        return getattr(config, "GAME_NAME", "Brawl Stars") or "Brawl Stars"

    @property
    def package_name(self) -> str:
        return getattr(config, "GAME_PACKAGE", "")

    @property
    def profile(self) -> GameProfile:
        return getattr(config, "SELECTED_GAME_PROFILE", None) or GameProfile(
            id="custom",
            name=self.game_name,
            package=self.package_name,
        )

    async def _open_play_store_page(self):
        """Open the exact Play Store details page before handing control to CV."""
        urls = (
            f"market://details?id={self.package_name}",
            f"https://play.google.com/store/apps/details?id={self.package_name}",
        )
        if hasattr(self.action, "_run_adb"):
            await self.action._run_adb(
                "shell",
                "am",
                "force-stop",
                "com.android.vending",
                timeout=10,
            )
            await asyncio.sleep(1)
            for url in urls:
                await self.action._run_adb(
                    "shell",
                    "am",
                    "start",
                    "-a",
                    "android.intent.action.VIEW",
                    "-d",
                    url,
                    "-p",
                    "com.android.vending",
                    timeout=15,
                )
                await asyncio.sleep(8)
                if await self._screen_looks_like_game_page():
                    logger.info(f"Opened Play Store details page via {url}")
                    return
                logger.warning(f"Play Store details page not confirmed after {url}")
            return

        await self.action.open_play_store(self.package_name)
        await asyncio.sleep(8)

    async def _screen_looks_like_game_page(self) -> bool:
        text = await self._visible_ui_text()
        return self.game_name.lower() in text or self.package_name.lower() in text

    async def _play_store_unavailable_reason(self) -> str:
        text = await self._visible_ui_text()
        if "недоступно в вашей стране" in text or "not available in your country" in text:
            return f"{self.game_name} is unavailable in this Play Store country"
        if "недоступно для вашего устройства" in text or "not available for your device" in text:
            return f"{self.game_name} is unavailable for this device"
        return ""

    async def _visible_ui_text(self) -> str:
        if not hasattr(self.action, "_run_adb"):
            return ""
        xml = await self.action._run_adb("exec-out", "uiautomator", "dump", "/dev/tty", timeout=25)
        return str(xml or "").lower()

    async def _tap_play_store_primary_button(self) -> bool:
        """Tap Install/Open using UI bounds before handing control to CV."""
        xml = await self._visible_ui_xml()
        if not xml:
            return False
        for keyword in ("Установить", "Install", "Обновить", "Update", "Открыть", "Open"):
            pos = self._find_clickable_text_center(xml, keyword)
            if not pos:
                continue
            logger.info(f"Play Store primary action '{keyword}' @ {pos}")
            await self.action.tap(pos[0], pos[1], pause=2.0)
            if keyword.lower() in {"open", "открыть"}:
                return True
            return True
        return False

    async def _visible_ui_xml(self) -> str:
        if not hasattr(self.action, "_run_adb"):
            return ""
        return await self.action._run_adb("exec-out", "uiautomator", "dump", "/dev/tty", timeout=25) or ""

    @staticmethod
    def _find_clickable_text_center(xml: str, keyword: str) -> tuple[int, int] | None:
        node_pattern = re.compile(r"<node\s[^>]*>", re.DOTALL)
        bounds_pattern = re.compile(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"')
        text_pattern = re.compile(r'text="([^"]*)"')
        desc_pattern = re.compile(r'content-desc="([^"]*)"')
        kw = keyword.lower()
        for match in node_pattern.finditer(xml):
            node = match.group(0)
            text = ""
            tm = text_pattern.search(node)
            dm = desc_pattern.search(node)
            if tm:
                text = tm.group(1)
            if not text and dm:
                text = dm.group(1)
            if kw not in text.lower():
                continue
            bm = bounds_pattern.search(node)
            if not bm:
                continue
            x1, y1, x2, y2 = map(int, bm.groups())
            if (x2 - x1) < 120 or (y2 - y1) < 40:
                continue
            return (x1 + x2) // 2, (y1 + y2) // 2
        return None

    async def _install_from_apk(self, apk_path: str):
        path = os.path.expanduser(apk_path)
        if not os.path.exists(path):
            raise RuntimeError(f"GAME_APK_PATH does not exist: {path}")
        self._log_step(f"Installing {self.game_name} APK from {path}")
        if hasattr(self.action, "_run_adb"):
            result = await self.action._run_adb("install", "-r", "-g", path, timeout=600)
            if "success" not in str(result).lower():
                raise RuntimeError(f"APK install failed: {result}")
            return
        ok = await self.action.install_apk(path)
        if not ok:
            raise RuntimeError("APK install failed")

    def _goal_text(self) -> str:
        template = getattr(config, "CV_INSTALL_GOAL_TEMPLATE", "") or INSTALL_GOAL_TEMPLATE
        profile_hints = " ".join((
            *self.profile.tutorial_hints,
            *self.profile.purchase_hints,
        ))
        return render_prompt_template(
            template,
            {
                "game_name": self.game_name,
                "package_name": self.package_name,
                "install_query": self.profile.install_query or self.game_name,
                "profile_hints": profile_hints,
                "operator_instructions": getattr(config, "CV_INSTALL_GOAL_EXTRA", ""),
            },
        )

    async def _wait_until_installed(self, timeout: int = 240):
        self._log_step(f"Waiting for {self.game_name} package to install")
        elapsed = 0
        while elapsed < timeout:
            if await self.action.is_package_installed(self.package_name):
                logger.success(f"{self.game_name} installed after {elapsed}s")
                return
            await asyncio.sleep(5)
            elapsed += 5
        raise RuntimeError(f"{self.game_name} install timeout")

    async def _launch_game(self):
        self._log_step(f"Launching {self.game_name}")
        await self.action.open_app(self.package_name)
        await asyncio.sleep(15)

    @staticmethod
    def _manual_fallback_enabled(error: RuntimeError) -> bool:
        if not getattr(config, "CV_FAILURE_FALLBACK_TO_MANUAL", False):
            return False
        return "CV models failed" in str(error)
