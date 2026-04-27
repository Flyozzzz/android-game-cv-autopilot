"""
Локальный Android эмулятор (AVD) через Appium.

Использует уже запущенный Appium сервер на localhost:4723
и подключается к локальному эмулятору (emulator-5554).
"""
import asyncio
import os
import shutil

from loguru import logger

import config


class LocalEmulatorFarm:
    """Управление локальным Android эмулятором через Appium."""

    def __init__(self):
        self.driver = None
        self.session_id = None
        self.device_serial = None

    @staticmethod
    def _adb_path() -> str:
        return (
            os.getenv("ADB_PATH")
            or shutil.which("adb")
            or "/Users/flyoz/Library/Android/sdk/platform-tools/adb"
        )

    @staticmethod
    def _parse_adb_devices(stdout: str) -> list[str]:
        devices: list[str] = []
        for line in stdout.strip().splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                devices.append(parts[0])
        return devices

    async def _connected_devices(self) -> list[str]:
        proc = await asyncio.create_subprocess_exec(
            self._adb_path(),
            "devices",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=5)
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode(errors="ignore").strip())
        return self._parse_adb_devices(stdout.decode(errors="ignore"))

    def _select_device(self, devices: list[str]) -> str:
        requested = (config.LOCAL_DEVICE or "").strip()
        if requested and requested.lower() not in ("auto", "first"):
            if requested not in devices:
                raise RuntimeError(
                    f"LOCAL_DEVICE={requested!r} is not connected. "
                    f"Connected devices: {', '.join(devices) or 'none'}"
                )
            return requested

        if len(devices) == 1:
            return devices[0]
        if not devices:
            raise RuntimeError("No Android devices connected")
        raise RuntimeError(
            "Multiple Android devices are connected. Set LOCAL_DEVICE to one of: "
            + ", ".join(devices)
        )

    async def check_api(self) -> bool:
        """Проверить что Appium сервер и эмулятор запущены."""
        import httpx

        appium_url = f"http://localhost:{config.APPIUM_PORT}"

        # 1. Check Appium server
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{appium_url}/status")
                if resp.status_code != 200:
                    logger.error(f"Appium server not running on {appium_url}")
                    return False
                status = resp.json()
                if not status.get("value", {}).get("ready"):
                    logger.error("Appium server not ready")
                    return False
                logger.info("Appium server: OK")
        except Exception as e:
            logger.error(f"Appium server check failed: {e}")
            logger.info(
                f"Start Appium with: appium --address 127.0.0.1 --port {config.APPIUM_PORT}"
            )
            return False

        # 2. Check emulator
        try:
            devices = await self._connected_devices()
            self.device_serial = self._select_device(devices)
            logger.info(f"Android device: {self.device_serial}")
        except Exception as e:
            logger.error(f"ADB check failed: {e}")
            return False

        return True

    async def start_session(self):
        """Создать Appium сессию на локальном эмуляторе."""
        from appium import webdriver
        from appium.options.android import UiAutomator2Options

        options = UiAutomator2Options()
        options.platform_name = "Android"
        options.automation_name = "UiAutomator2"
        options.no_reset = True
        options.auto_grant_permissions = True
        if not self.device_serial:
            self.device_serial = self._select_device(await self._connected_devices())
        options.device_name = self.device_serial
        options.udid = self.device_serial
        options.new_command_timeout = 300  # 5 min — long enough for SMS waits
        options.set_capability("appium:adbExecTimeout", 120000)
        options.set_capability("appium:androidInstallTimeout", 120000)
        options.set_capability("appium:uiautomator2ServerInstallTimeout", 120000)
        options.set_capability("appium:uiautomator2ServerLaunchTimeout", 120000)

        # Don't specify app — we want home screen
        # The bot opens Settings/Play Store itself

        appium_url = f"http://localhost:{config.APPIUM_PORT}"

        logger.info(
            f"Starting local Appium session: "
            f"{options.device_name} on {appium_url}"
        )

        loop = asyncio.get_event_loop()
        self.driver = await loop.run_in_executor(
            None,
            lambda: webdriver.Remote(
                command_executor=appium_url,
                options=options,
            ),
        )
        self.session_id = self.driver.session_id
        logger.success(f"Local Appium session started: {self.session_id}")

        # Switch to NATIVE_APP context
        try:
            ctx = await loop.run_in_executor(
                None, lambda: self.driver.current_context
            )
            logger.info(f"Current context: {ctx}")
        except Exception:
            pass

        return self.driver

    async def stop_session(self):
        """Остановить Appium сессию."""
        if self.driver:
            try:
                self.driver.quit()
                logger.info("Local Appium session stopped")
            except Exception as e:
                logger.debug(f"Session quit error: {e}")
            self.driver = None

    async def close(self):
        """Закрыть HTTP-клиенты (no-op для local)."""
        pass
