"""Manual checkpoint controlled from the local dashboard."""
from __future__ import annotations

import asyncio
from pathlib import Path
import time

from loguru import logger

import config
from scenarios.base import BaseScenario


class ManualControlScenario(BaseScenario):
    """Pause automation while the user controls the device from the dashboard."""

    NAME = "manual_control"

    def __init__(self, cv, action, *, stage_name: str, hint: str = ""):
        super().__init__(cv, action)
        self.stage_name = stage_name
        self.hint = hint

    async def run(self) -> bool:
        signal_path = Path(getattr(config, "MANUAL_CONTROL_SIGNAL_FILE", "dashboard/manual_continue.flag"))
        timeout = int(getattr(config, "MANUAL_CONTROL_TIMEOUT_SECONDS", 600))
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        if signal_path.exists():
            signal_path.unlink()

        logger.info("=" * 50)
        logger.info(f"SCENARIO: Manual control checkpoint ({self.stage_name})")
        logger.info("=" * 50)
        logger.info(
            "Manual mode active. Open the dashboard manual screen, control the "
            "phone, then press Continue Automation."
        )
        if self.hint:
            logger.info(f"Manual hint: {self.hint}")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if signal_path.exists():
                try:
                    signal_path.unlink()
                except Exception:
                    pass
                logger.success(f"Manual checkpoint complete: {self.stage_name}")
                return True
            await asyncio.sleep(1.0)

        raise RuntimeError(
            f"Manual checkpoint timed out after {timeout}s: {self.stage_name}"
        )
