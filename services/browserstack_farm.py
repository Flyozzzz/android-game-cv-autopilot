"""
BrowserStack App Automate — реальные Android устройства с Play Market.
Запускает Appium-сессию через hub-cloud.browserstack.com.
"""
from __future__ import annotations

import asyncio
from loguru import logger

import config


class BrowserStackFarm:
    """
    Клиент для BrowserStack App Automate (реальные Android устройства).
    Создаёт Appium WebDriver сессию и возвращает driver для AppiumActionEngine.
    """

    HUB_URL = "https://hub-cloud.browserstack.com/wd/hub"

    def __init__(self):
        self.driver = None
        self.session_id = None

    def _hub_url(self) -> str:
        """URL с credentials встроенными — самый надёжный способ авторизации."""
        u = config.BROWSERSTACK_USERNAME
        k = config.BROWSERSTACK_ACCESS_KEY
        return f"https://{u}:{k}@hub-cloud.browserstack.com/wd/hub"

    async def start_session(self):
        """
        Запустить Appium-сессию на реальном Android устройстве BrowserStack.
        Возвращает Appium WebDriver (передаётся в AppiumActionEngine).
        """
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.no_reset = True
        options.auto_grant_permissions = True

        # BrowserStack W3C namespace с deviceName/osVersion
        options.set_capability("bstack:options", {
            "userName": config.BROWSERSTACK_USERNAME,
            "accessKey": config.BROWSERSTACK_ACCESS_KEY,
            "deviceName": config.BROWSERSTACK_DEVICE,
            "osVersion": config.BROWSERSTACK_OS_VERSION,
            "deviceOrientation": "portrait",
            "debug": True,
            "networkLogs": True,
        })

        logger.info(
            f"Starting BrowserStack session: {config.BROWSERSTACK_DEVICE} "
            f"Android {config.BROWSERSTACK_OS_VERSION}"
        )

        loop = asyncio.get_event_loop()
        self.driver = await loop.run_in_executor(
            None,
            lambda: webdriver.Remote(self.HUB_URL, options=options),
        )
        self.session_id = self.driver.session_id
        logger.success(f"BrowserStack session started: {self.session_id}")

        # Session starts in ChromeDriver mode (Chrome is the default app).
        # Switch Appium context to NATIVE_APP so UiAutomator2 takes over —
        # this allows activate_app/screenshot without ChromeDriver screenshot lock.
        try:
            await loop.run_in_executor(
                None,
                lambda: self.driver.switch_to.context("NATIVE_APP"),
            )
            logger.info("Switched context to NATIVE_APP (UiAutomator2)")
        except Exception as e:
            logger.debug(f"Context switch: {e}")

        # Force PORTRAIT orientation — BrowserStack may start in landscape
        try:
            def _set_portrait():
                self.driver.orientation = "PORTRAIT"
            await loop.run_in_executor(None, _set_portrait)
            await asyncio.sleep(1)
            logger.info("Orientation set to PORTRAIT")
        except Exception as e:
            logger.debug(f"Orientation set: {e}")

        # Open Settings (lightweight app) to get away from Chrome's renderer
        try:
            await loop.run_in_executor(
                None,
                lambda: self.driver.activate_app("com.android.settings"),
            )
            await asyncio.sleep(5)
            # Verify screenshot is non-white (retry up to 5 times)
            for attempt in range(5):
                png = await loop.run_in_executor(
                    None,
                    lambda: self.driver.get_screenshot_as_png(),
                )
                if png and len(png) > 20000:
                    logger.info(f"Session ready: Settings rendered ({len(png)} bytes)")
                    break
                logger.debug(f"Settings not rendered yet (attempt {attempt+1}, {len(png or b'')} bytes), waiting 3s...")
                await asyncio.sleep(3)
        except Exception as e:
            logger.warning(f"Session warmup failed: {e}")

        return self.driver

    async def stop_session(self):
        """Завершить Appium-сессию."""
        if not self.driver:
            return
        session_id = self.session_id
        logger.info(f"Stopping BrowserStack session {session_id}...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.driver.quit)
            logger.success(f"BrowserStack session {session_id} stopped")
        except Exception as e:
            logger.error(f"Error stopping BrowserStack session: {e}")
        finally:
            self.driver = None

    async def close(self):
        await self.stop_session()

    async def check_api(self) -> bool:
        """Проверить BrowserStack учётные данные через REST API."""
        import httpx
        if not config.BROWSERSTACK_USERNAME or not config.BROWSERSTACK_ACCESS_KEY:
            logger.warning("BrowserStack: BROWSERSTACK_USERNAME / BROWSERSTACK_ACCESS_KEY не заданы")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.browserstack.com/automate/plan.json",
                    auth=(config.BROWSERSTACK_USERNAME, config.BROWSERSTACK_ACCESS_KEY),
                )
                if resp.status_code == 200:
                    data = resp.json()
                    logger.success(
                        f"BrowserStack API: OK "
                        f"(parallel={data.get('parallel_sessions_max_allowed', '?')}, "
                        f"plan={data.get('automate_plan', '?')})"
                    )
                    return True
                logger.error(
                    f"BrowserStack API: HTTP {resp.status_code} — {resp.text[:200]}"
                )
                return False
        except Exception as e:
            logger.error(f"BrowserStack API error: {e}")
            return False
