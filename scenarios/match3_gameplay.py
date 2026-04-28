"""Generic match-3 gameplay helper."""
from __future__ import annotations

import asyncio

from loguru import logger

import config
from core.frame_source import AdbScreencapSource
from core.match3_solver import cell_center, classify_board_from_png, find_best_swap
from core.perception.screen_stability import ScreenStabilityDetector, wait_until_stable
from scenarios.base import BaseScenario


class Match3GameplayScenario(BaseScenario):
    """Classify a visible match-3 grid and perform safe adjacent swaps."""

    NAME = "match3_gameplay"

    async def run(self) -> bool:
        rows = int(getattr(config, "MATCH3_GRID_ROWS", 9))
        cols = int(getattr(config, "MATCH3_GRID_COLS", 9))
        max_moves = int(getattr(config, "MATCH3_MAX_MOVES", 12))
        bounds = self._bounds_from_config()
        stability_enabled = bool(getattr(config, "MATCH3_STABILITY_ENABLED", True))
        stability_timeout_ms = int(getattr(config, "MATCH3_STABILITY_TIMEOUT_MS", 1200))
        stability_poll_ms = int(getattr(config, "MATCH3_STABILITY_POLL_MS", 80))
        frame_source = AdbScreencapSource(action=self.action)

        logger.info("=" * 50)
        logger.info(f"SCENARIO: Match-3 Gameplay ({rows}x{cols}, moves={max_moves})")
        logger.info("=" * 50)

        moves_done = 0
        for move_index in range(1, max_moves + 1):
            if stability_enabled:
                stability = await wait_until_stable(
                    frame_source,
                    detector=ScreenStabilityDetector(window_size=2),
                    timeout_ms=stability_timeout_ms,
                    poll_interval_ms=stability_poll_ms,
                    roi=bounds,
                )
                if not stability.stable:
                    logger.warning(
                        "Match-3 board is not stable; skipping next move "
                        f"(reason={stability.reason}, diff={stability.mean_diff})"
                    )
                    break
            screenshot = await self.action.screenshot()
            classified = classify_board_from_png(
                screenshot,
                rows=rows,
                cols=cols,
                bounds=bounds,
            )
            swap = find_best_swap(classified.board)
            if not swap:
                logger.warning("No match-3 swap found on current board")
                break
            first, second = swap
            x1, y1 = cell_center(classified, first)
            x2, y2 = cell_center(classified, second)
            logger.info(f"Match-3 move {move_index}: {first}->{second} ({x1},{y1}) to ({x2},{y2})")
            await self.action.swipe(x1, y1, x2, y2, duration_ms=140)
            moves_done += 1
            await asyncio.sleep(1.0)

        logger.success(f"Match-3 helper complete: moves={moves_done}")
        return True

    @staticmethod
    def _bounds_from_config() -> tuple[int, int, int, int] | None:
        raw = str(getattr(config, "MATCH3_GRID_BOUNDS", "") or "").strip()
        if not raw:
            return None
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) != 4:
            raise RuntimeError("MATCH3_GRID_BOUNDS must be x1,y1,x2,y2")
        try:
            x1, y1, x2, y2 = (int(p) for p in parts)
        except ValueError as e:
            raise RuntimeError("MATCH3_GRID_BOUNDS must contain integers") from e
        if x2 <= x1 or y2 <= y1:
            raise RuntimeError("MATCH3_GRID_BOUNDS must have x2>x1 and y2>y1")
        return x1, y1, x2, y2
