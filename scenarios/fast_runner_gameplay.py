"""Realtime-ish gameplay loop for simple lane runner games."""
from __future__ import annotations

import asyncio
import time

from loguru import logger

import config
from core.frame_source import close_frame_source, create_frame_source, infer_frame_source_serial
from core.gameplay.runner_plugin import RunnerPlugin
from core.input_scheduler import InputScheduler
from core.metrics import record_latency
from scenarios.base import BaseScenario


class FastRunnerGameplayScenario(BaseScenario):
    """Use local screenshot heuristics for runner gameplay gestures."""

    NAME = "fast_runner_gameplay"

    async def run(self) -> bool:
        seconds = float(getattr(config, "FAST_GAMEPLAY_SECONDS", 35.0))
        frame_delay = float(getattr(config, "FAST_GAMEPLAY_FRAME_DELAY", 0.05))
        runner = RunnerPlugin()
        scheduler = InputScheduler(self.action, mode="fast")
        frame_source = create_frame_source(
            action=self.action,
            serial=infer_frame_source_serial(self.action),
        )

        logger.info("=" * 50)
        logger.info(f"SCENARIO: Fast Runner Gameplay ({seconds:.1f}s)")
        logger.info("=" * 50)

        width, height = self._screen_size()
        deadline = time.monotonic() + seconds
        gesture_count = 0
        frame_count = 0

        try:
            while time.monotonic() < deadline:
                loop_started = time.perf_counter()
                frame_count += 1
                frame = await frame_source.latest_frame()
                width, height = frame.width, frame.height
                decision = runner.decide(frame)
                if not decision.action.is_noop:
                    x1, y1, x2, y2 = runner.gesture_points(width, height, decision.action.gesture)
                    result = await scheduler.swipe(
                        x1,
                        y1,
                        x2,
                        y2,
                        duration_ms=90,
                        cooldown_key=decision.action.cooldown_key,
                    )
                    if result.executed:
                        logger.info(
                            f"Runner gesture={decision.action.gesture} state={decision.state.value} scores="
                            f"{tuple(round(s, 1) for s in decision.lane_scores)} "
                            f"velocity={tuple(round(s, 1) for s in decision.score_velocity)} "
                            f"reason={decision.action.reason}"
                        )
                        gesture_count += 1
                loop_total_ms = (time.perf_counter() - loop_started) * 1000.0
                record_latency("loop_total_ms", loop_total_ms)
                if loop_total_ms > 0:
                    record_latency("fps", 1000.0 / loop_total_ms)
                await asyncio.sleep(max(0.01, frame_delay))
        finally:
            close_frame_source(frame_source)

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
