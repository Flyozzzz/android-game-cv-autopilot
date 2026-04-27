"""Realtime-ish gameplay loop for simple lane runner games."""
from __future__ import annotations

import asyncio
import time

from loguru import logger

import config
from core.fast_runner import FastRunnerDetector
from scenarios.base import BaseScenario


class FastRunnerGameplayScenario(BaseScenario):
    """Use local screenshot heuristics for runner gameplay gestures."""

    NAME = "fast_runner_gameplay"

    async def run(self) -> bool:
        seconds = float(getattr(config, "FAST_GAMEPLAY_SECONDS", 35.0))
        frame_delay = float(getattr(config, "FAST_GAMEPLAY_FRAME_DELAY", 0.05))
        detector = FastRunnerDetector()

        logger.info("=" * 50)
        logger.info(f"SCENARIO: Fast Runner Gameplay ({seconds:.1f}s)")
        logger.info("=" * 50)

        width, height = self._screen_size()
        gestures = {
            "left": (int(width * 0.55), int(height * 0.74), int(width * 0.25), int(height * 0.74)),
            "right": (int(width * 0.45), int(height * 0.74), int(width * 0.75), int(height * 0.74)),
            "up": (int(width * 0.50), int(height * 0.76), int(width * 0.50), int(height * 0.42)),
            "down": (int(width * 0.50), int(height * 0.42), int(width * 0.50), int(height * 0.78)),
        }

        deadline = time.monotonic() + seconds
        last_gesture_at = 0.0
        gesture_count = 0
        frame_count = 0

        while time.monotonic() < deadline:
            frame_count += 1
            screenshot = await self.action.screenshot()
            decision = detector.decide(screenshot)
            now = time.monotonic()
            if decision.gesture != "none" and now - last_gesture_at >= 0.22:
                x1, y1, x2, y2 = gestures[decision.gesture]
                logger.info(
                    f"Runner gesture={decision.gesture} scores="
                    f"{tuple(round(s, 1) for s in decision.lane_scores)} "
                    f"reason={decision.reason}"
                )
                await self.action.swipe(x1, y1, x2, y2, duration_ms=90)
                last_gesture_at = now
                gesture_count += 1
            await asyncio.sleep(max(0.01, frame_delay))

        logger.success(
            f"Fast runner loop complete: frames={frame_count}, gestures={gesture_count}"
        )
        return True

    def _screen_size(self) -> tuple[int, int]:
        try:
            width = int(getattr(self.action, "_real_screen_w", 0) or 0)
            height = int(getattr(self.action, "_real_screen_h", 0) or 0)
        except Exception:
            width = height = 0
        if width > 0 and height > 0:
            return width, height
        return int(getattr(config, "SCREEN_WIDTH", 1080)), int(getattr(config, "SCREEN_HEIGHT", 2400))
