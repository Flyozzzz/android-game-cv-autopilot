"""Action scheduler with mode-aware pauses and gesture cooldowns."""
from __future__ import annotations

from dataclasses import dataclass
import inspect
import time
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import config


ActionMode = Literal["menu", "fast"]


DEFAULT_COOLDOWNS_MS = {
    "lane_change": 180.0,
    "jump": 350.0,
    "duck": 300.0,
    "tap_confirm": 300.0,
}


@dataclass(frozen=True)
class ScheduledActionResult:
    action: str
    executed: bool
    reason: str = ""
    cooldown_key: str = ""
    remaining_ms: float = 0.0


class InputScheduler:
    """Execute Android inputs without spamming gestures in fast loops."""

    def __init__(
        self,
        action: Any,
        *,
        mode: ActionMode | None = None,
        cooldowns_ms: Mapping[str, float] | None = None,
        clock: Any | None = None,
    ):
        self.action = action
        configured_mode = (mode or getattr(config, "ACTION_MODE", "menu") or "menu").strip().lower()
        self.mode: ActionMode = "fast" if configured_mode == "fast" else "menu"
        merged = dict(DEFAULT_COOLDOWNS_MS)
        if cooldowns_ms:
            merged.update({str(k): float(v) for k, v in cooldowns_ms.items()})
        self.cooldowns_ms = merged
        self._last_executed_ms: dict[str, float] = {}
        self._clock = clock or time.monotonic

    def remaining_cooldown_ms(self, cooldown_key: str) -> float:
        if not cooldown_key:
            return 0.0
        cooldown = max(0.0, float(self.cooldowns_ms.get(cooldown_key, 0.0)))
        last = self._last_executed_ms.get(cooldown_key)
        if last is None or cooldown <= 0:
            return 0.0
        elapsed = self._now_ms() - last
        return max(0.0, cooldown - elapsed)

    async def tap(
        self,
        x: int,
        y: int,
        *,
        mode: ActionMode | None = None,
        cooldown_key: str = "",
        pause: float | None = None,
    ) -> ScheduledActionResult:
        blocked = self._cooldown_result("tap", cooldown_key)
        if blocked:
            return blocked
        effective_mode = self._mode(mode)
        effective_pause = self._pause(effective_mode, pause)
        await self.action.tap(int(x), int(y), pause=effective_pause)
        self._mark_executed(cooldown_key)
        return ScheduledActionResult("tap", True, cooldown_key=cooldown_key)

    async def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        *,
        duration_ms: int = 300,
        mode: ActionMode | None = None,
        cooldown_key: str = "",
        pause: float | None = None,
    ) -> ScheduledActionResult:
        blocked = self._cooldown_result("swipe", cooldown_key)
        if blocked:
            return blocked
        effective_mode = self._mode(mode)
        effective_pause = self._pause(effective_mode, pause)
        await self._call_swipe(
            int(x1),
            int(y1),
            int(x2),
            int(y2),
            int(duration_ms),
            effective_pause,
        )
        self._mark_executed(cooldown_key)
        return ScheduledActionResult("swipe", True, cooldown_key=cooldown_key)

    async def batch(self, actions: Sequence[Mapping[str, Any]]) -> list[ScheduledActionResult]:
        results: list[ScheduledActionResult] = []
        for item in actions:
            action_type = str(item.get("type") or item.get("action") or "").strip().lower()
            if action_type == "tap":
                results.append(
                    await self.tap(
                        int(item["x"]),
                        int(item["y"]),
                        mode=item.get("mode"),
                        cooldown_key=str(item.get("cooldown_key") or ""),
                        pause=item.get("pause"),
                    )
                )
            elif action_type == "swipe":
                results.append(
                    await self.swipe(
                        int(item["x1"]),
                        int(item["y1"]),
                        int(item["x2"]),
                        int(item["y2"]),
                        duration_ms=int(item.get("duration_ms", 300)),
                        mode=item.get("mode"),
                        cooldown_key=str(item.get("cooldown_key") or ""),
                        pause=item.get("pause"),
                    )
                )
            else:
                results.append(
                    ScheduledActionResult(
                        action=action_type or "unknown",
                        executed=False,
                        reason="unsupported_action",
                    )
                )
        return results

    def _mode(self, override: ActionMode | None) -> ActionMode:
        return "fast" if override == "fast" else "menu" if override == "menu" else self.mode

    @staticmethod
    def _pause(mode: ActionMode, override: float | None) -> float:
        if override is not None:
            return max(0.0, float(override))
        return 0.0 if mode == "fast" else 0.3

    async def _call_swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int,
        pause: float,
    ) -> None:
        params = inspect.signature(self.action.swipe).parameters
        if "pause" in params:
            await self.action.swipe(x1, y1, x2, y2, duration_ms=duration_ms, pause=pause)
            return
        await self.action.swipe(x1, y1, x2, y2, duration_ms=duration_ms)

    def _cooldown_result(
        self,
        action: str,
        cooldown_key: str,
    ) -> ScheduledActionResult | None:
        remaining = self.remaining_cooldown_ms(cooldown_key)
        if remaining > 0:
            return ScheduledActionResult(
                action,
                False,
                reason="cooldown",
                cooldown_key=cooldown_key,
                remaining_ms=round(remaining, 3),
            )
        return None

    def _mark_executed(self, cooldown_key: str) -> None:
        if cooldown_key:
            self._last_executed_ms[cooldown_key] = self._now_ms()

    def _now_ms(self) -> float:
        return float(self._clock()) * 1000.0
