"""Manual, user-controlled phone/SMS verification helpers.

This module is for legal flows where the user supplies their own reachable phone
number and SMS code. It does not buy, rotate, or try disposable numbers.
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Callable

from loguru import logger


_CODE_RE = re.compile(r"(?:G-)?\b(\d{5,8})\b")


class ManualVerification:
    """Get a real phone number and SMS code from env/file/stdin."""

    def __init__(
        self,
        input_func: Callable[[str], str] | None = input,
        env: dict[str, str] | None = None,
    ):
        self.input_func = input_func
        self.env = env if env is not None else os.environ

    def phone_data(self) -> dict:
        """Return phone data shaped like SMSService.buy_number()."""
        phone = (self.env.get("GOOGLE_PHONE_NUMBER") or "").strip()
        if not phone and self.input_func:
            phone = self.input_func(
                "Enter your real phone number for Google verification (E.164, e.g. +15551234567): "
            ).strip()
        if not phone:
            raise RuntimeError(
                "GOOGLE_PHONE_NUMBER is required for manual legal phone verification "
                "when running non-interactively."
            )
        return {
            "id": "manual",
            "phone": phone,
            "operator": "manual",
            "status": "MANUAL",
            "price": 0,
        }

    async def wait_for_code(self, timeout: int = 300, poll_interval: float = 3.0) -> str:
        """Wait for a user-provided SMS code.

        Sources, in priority order:
        1. GOOGLE_SMS_CODE env var
        2. GOOGLE_SMS_CODE_FILE file contents (polled until timeout)
        3. stdin prompt, when input_func is provided
        """
        env_code = self._extract_code(self.env.get("GOOGLE_SMS_CODE") or "")
        if env_code:
            return env_code

        code_file = (self.env.get("GOOGLE_SMS_CODE_FILE") or "").strip()
        if code_file:
            logger.info(f"Waiting for manual SMS code in file: {code_file}")
            deadline = asyncio.get_event_loop().time() + timeout
            path = Path(code_file)
            while asyncio.get_event_loop().time() < deadline:
                if path.exists():
                    code = self._extract_code(path.read_text(errors="ignore"))
                    if code:
                        return code
                await asyncio.sleep(poll_interval)
            raise TimeoutError(f"Manual SMS code file did not contain a code in {timeout}s: {code_file}")

        if self.input_func:
            raw = self.input_func("Enter Google SMS verification code: ").strip()
            code = self._extract_code(raw)
            if code:
                return code

        raise RuntimeError(
            "GOOGLE_SMS_CODE or GOOGLE_SMS_CODE_FILE is required for manual SMS verification "
            "when running non-interactively."
        )

    @staticmethod
    def _extract_code(text: str) -> str:
        match = _CODE_RE.search(text or "")
        return match.group(1) if match else ""
