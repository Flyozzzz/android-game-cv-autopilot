"""
LambdaTest Real Devices — реальные Android устройства с Play Market.
Запускает Appium-сессию через mobile-hub.lambdatest.com.
"""
from __future__ import annotations

import asyncio
from loguru import logger
from appium.webdriver.common.appiumby import AppiumBy

import config


class LambdaTestFarm:
    """
    Клиент для LambdaTest Real Device Appium.
    Создаёт Appium WebDriver сессию и возвращает driver для AppiumActionEngine.
    """

    HUB_URL = "https://mobile-hub.lambdatest.com/wd/hub"

    def __init__(self):
        self.driver = None
        self.session_id = None

    @property
    def hub_url_with_auth(self):
        """Hub URL с встроенными credentials (Basic Auth)."""
        return (
            f"https://{config.LT_USERNAME}:{config.LT_ACCESS_KEY}"
            f"@mobile-hub.lambdatest.com/wd/hub"
        )

    async def start_session(self):
        """
        Запустить Appium-сессию на реальном Android устройстве LambdaTest.
        Возвращает Appium WebDriver (передаётся в AppiumActionEngine).
        """
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
        from appium.webdriver.client_config import AppiumClientConfig

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.no_reset = True
        options.auto_grant_permissions = True

        # LambdaTest W3C capabilities — ВСЁ внутри lt:options (lowercase!)
        # Креды передаются ВНУТРИ lt:options, не в hub URL
        # Точный формат как в lt_ss_final.py (проверено, работает)
        options.set_capability("lt:options", {
            "user": config.LT_USERNAME,
            "accessKey": config.LT_ACCESS_KEY,
            "deviceName": config.LT_DEVICE,
            "platformVersion": config.LT_OS_VERSION,
            "deviceOrientation": "portrait",
            "build": "android-automation",
            "name": "google-play-pipeline",
            "app": "lt://APP1016025301776984651652935",
            "commandTimeout": 900,
            "idleTimeout": 1800,
        })

        # Hub URL БЕЗ credentials (они в lt:options)
        hub_url = "https://mobile-hub.lambdatest.com/wd/hub"

        # CRITICAL: Set long timeout BEFORE session creation.
        # LambdaTest real devices can take 60-120s to allocate.
        # Without this the client disconnects while waiting in queue.
        client_config = AppiumClientConfig(
            remote_server_addr=hub_url,
            timeout=300,
            direct_connection=False,
        )

        logger.info(
            f"Starting LambdaTest session: {config.LT_DEVICE} "
            f"Android {config.LT_OS_VERSION} (isRealMobile=True, client_timeout=300s)"
        )

        loop = asyncio.get_event_loop()
        self.driver = await loop.run_in_executor(
            None,
            lambda: webdriver.Remote(
                command_executor=hub_url,
                options=options,
                client_config=client_config,
            ),
        )
        # Post-creation: set even longer timeout for individual commands
        try:
            import urllib3
            self.driver.command_executor._client_config.__dict__['_timeout'] = 60
            self.driver.command_executor._conn.connection_pool_kw['timeout'] = urllib3.util.Timeout(total=60)
            logger.info("HTTP command timeout = 60s")
        except Exception as e:
            logger.debug(f"Could not set post-creation timeout: {e}")
        self.session_id = self.driver.session_id
        logger.success(f"LambdaTest session started: {self.session_id}")

        # Switch to NATIVE_APP context for UiAutomator2
        try:
            await loop.run_in_executor(
                None,
                lambda: self.driver.switch_to.context("NATIVE_APP"),
            )
            logger.info("Switched context to NATIVE_APP (UiAutomator2)")
        except Exception as e:
            logger.debug(f"Context switch: {e}")

        # Force PORTRAIT orientation
        try:
            def _set_portrait():
                self.driver.orientation = "PORTRAIT"
            await loop.run_in_executor(None, _set_portrait)
            await asyncio.sleep(1)
            logger.info("Orientation set to PORTRAIT")
        except Exception as e:
            logger.debug(f"Orientation set: {e}")

        # Quick warmup: activate Settings and verify via page source (faster than screenshot)
        try:
            await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: self.driver.activate_app("com.android.settings"),
                ),
                timeout=20,
            )
            await asyncio.sleep(3)
            # Verify session is alive via find_element (page_source HANGS on LambdaTest)
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        lambda: self.driver.find_element(
                            AppiumBy.ANDROID_UIAUTOMATOR,
                            'new UiSelector().packageName("com.android.settings")'
                        ),
                    ),
                    timeout=10,
                )
                logger.info("Session ready: Settings UI verified")
            except Exception:
                logger.info("Session warmup: Settings launched (UI check skipped)")
        except Exception as e:
            logger.warning(f"Session warmup skipped: {e}")

        return self.driver

    async def stop_session(self):
        """Завершить Appium-сессию."""
        if not self.driver:
            return
        session_id = self.session_id
        logger.info(f"Stopping LambdaTest session {session_id}...")
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self.driver.quit)
            logger.success(f"LambdaTest session {session_id} stopped")
        except Exception as e:
            logger.error(f"Error stopping LambdaTest session: {e}")
        finally:
            self.driver = None

    async def close(self):
        await self.stop_session()

    async def check_api(self) -> bool:
        """Проверить LambdaTest учётные данные через REST API."""
        import httpx
        if not config.LT_USERNAME or not config.LT_ACCESS_KEY:
            logger.warning("LambdaTest: LT_USERNAME / LT_ACCESS_KEY не заданы")
            return False
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.lambdatest.com/automation/api/v1/builds",
                    auth=(config.LT_USERNAME, config.LT_ACCESS_KEY),
                )
                if resp.status_code == 200:
                    logger.success(
                        f"LambdaTest API: OK (user={config.LT_USERNAME})"
                    )
                    return True
                logger.error(
                    f"LambdaTest API: HTTP {resp.status_code} — {resp.text[:200]}"
                )
                return False
        except Exception as e:
            logger.error(f"LambdaTest API error: {e}")
            return False
