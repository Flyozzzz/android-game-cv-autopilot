"""Google account signup driven by CV autopilot."""
from __future__ import annotations

import asyncio

from loguru import logger

import config
from core.cv_autopilot import CVAutopilot
from core.cv_engine import CVEngine
from scenarios.google_register import GoogleRegisterScenario
from scenarios.phone_checkpoint import PhoneVerificationReached


SIGNUP_URL = (
    "https://accounts.google.com/signup/v2/webcreateaccount"
    "?flowName=GlifWebSignIn&flowEntry=SignUp"
)


class GoogleRegisterCVScenario(GoogleRegisterScenario):
    """Register a Google account through screenshots and Vision-planned actions."""

    NAME = "google_register_cv"

    async def run(self):
        logger.info("=" * 60)
        logger.info("  SCENARIO: Register NEW Google Account (CV autopilot)")
        logger.info("=" * 60)

        if not self._has_cv_api_key():
            raise RuntimeError(
                "CV autopilot requires OPENROUTER_API_KEY. "
                "Set it in the environment before GOOGLE_REGISTER_VIA=cv."
            )

        self.credentials = self.creds_gen.generate()
        logger.info(f"  Name:     {self.credentials['first_name']} {self.credentials['last_name']}")
        logger.info(f"  Email:    {self.credentials['full_email']}")
        logger.info(
            f"  Birthday: {self.credentials['birth_year']}-"
            f"{self.credentials['birth_month']}-{self.credentials['birth_day']}"
        )

        self.phone_data = await self._prepare_phone_data()
        browser_package = await self._open_signup_page()

        autopilot = CVAutopilot(
            action=self.action,
            cv=CVEngine(),
            max_steps=getattr(config, "CV_AUTOPILOT_MAX_STEPS", 45),
            allow_risky_actions=False,
        )
        values = dict(self._signup_values())
        values["signup_url"] = SIGNUP_URL
        values["browser_package"] = browser_package
        values["clear_before_type"] = "1"
        if browser_package == "org.mozilla.firefox":
            values["coordinate_scale"] = getattr(config, "CV_COORDINATE_SCALE", "1.53")
        result = await autopilot.run(self._goal_text(), values)
        logger.info(f"CV autopilot result: {result.status} ({result.reason})")

        if not result.ok:
            raise RuntimeError(f"CV autopilot failed: {result.reason}")

        if getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False):
            raise PhoneVerificationReached(stage="phone_input")

        config.GOOGLE_EMAIL = self.credentials["full_email"]
        config.GOOGLE_PASSWORD = self.credentials["password"]
        return self.credentials

    @staticmethod
    def _has_cv_api_key() -> bool:
        key = (getattr(config, "OPENROUTER_API_KEY", "") or "").strip()
        return bool(key and key != "sk-or-...d41a")

    async def _open_signup_page(self) -> str:
        """Open signup in a browser that CV can see without clearing user data."""
        self._log_step("Opening Google signup for CV autopilot")
        if getattr(config, "DEVICE_FARM", "local") == "local":
            browser_package = await self._local_browser_package()
            await self.action._run_adb("shell", "am", "force-stop", browser_package, timeout=5)
            if browser_package == "org.mozilla.firefox":
                await self.action._run_adb(
                    "shell",
                    (
                        "am start -S --activity-clear-task "
                        "-a android.intent.action.VIEW "
                        f"-d '{SIGNUP_URL}' -p org.mozilla.firefox"
                    ),
                    timeout=15,
                )
                await asyncio.sleep(10)
                return browser_package

            # Chrome can be signed into an existing Google account, but keep this
            # fallback for devices without Firefox installed.
            await self.action._run_adb("shell", "am", "force-stop", "com.android.chrome", timeout=5)
            await self.action._run_adb("shell", "am", "force-stop", "com.mi.globalbrowser", timeout=5)
            await self.action._run_adb(
                "shell",
                "am",
                "start",
                "-S",
                "--activity-clear-task",
                "-n",
                "com.android.chrome/com.google.android.apps.chrome.IntentDispatcher",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                SIGNUP_URL,
                timeout=10,
            )
            await asyncio.sleep(6)
            return browser_package
        else:
            await self.action.open_url(SIGNUP_URL)
            await asyncio.sleep(6)
            return "com.android.chrome"

    async def _local_browser_package(self) -> str:
        firefox = await self.action._run_adb("shell", "pm", "path", "org.mozilla.firefox", timeout=5)
        if firefox:
            return "org.mozilla.firefox"
        return "com.android.chrome"

    def _goal_text(self) -> str:
        stop_at_phone = getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False)
        phone_instruction = (
            "Stop with action=done as soon as the page asks for phone verification; "
            "do not enter a phone number."
            if stop_at_phone
            else "If phone verification appears, enter the provided phone value and continue."
        )
        return (
            "Create a new Google account in Chrome using the available values. "
            "If Chrome is not showing the Google signup page, tap the address bar, "
            "type text_value_key=signup_url, and press enter. "
            "Fill first name, last name, birthday, gender, Gmail username, and password. "
            "Use text_value_key from AVAILABLE_VALUES_JSON for all typing. "
            "Use done only when the account is created or when instructed to stop at phone verification. "
            f"{phone_instruction}"
        )
