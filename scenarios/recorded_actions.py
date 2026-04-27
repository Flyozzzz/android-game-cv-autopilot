"""Replay manually recorded dashboard actions."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from scenarios.base import BaseScenario


RISKY_REPLAY_WORDS = (
    "buy",
    "pay",
    "purchase",
    "confirm",
    "subscribe",
    "купить",
    "оплат",
    "подтверд",
)


class RecordedActionsScenario(BaseScenario):
    """Replay a saved action list against the current Android device."""

    NAME = "recorded_actions"

    def __init__(self, cv, action, *, stage_name: str, recording_path: str):
        super().__init__(cv, action)
        self.stage_name = stage_name
        self.recording_path = recording_path

    async def run(self) -> bool:
        path = Path(self.recording_path).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.exists():
            raise RuntimeError(f"Recorded actions file not found: {path}")

        payload = json.loads(path.read_text())
        actions = payload.get("actions") if isinstance(payload, dict) else payload
        if not isinstance(actions, list) or not actions:
            raise RuntimeError(f"Recorded actions file has no actions: {path}")

        if self.stage_name == "purchase_preview":
            self._refuse_risky_purchase_replay(actions)

        logger.info("=" * 50)
        logger.info(f"SCENARIO: Replay recorded actions ({self.stage_name})")
        logger.info("=" * 50)
        logger.info(f"Recording: {path} ({len(actions)} actions)")

        for index, item in enumerate(actions, start=1):
            await self._replay_one(index, item)
        return True

    async def _replay_one(self, index: int, item: dict[str, Any]) -> None:
        action = str(item.get("action") or "").lower()
        pause = float(item.get("pause") or item.get("delay") or 0.45)
        logger.info(f"Replay action {index}: {action} {item}")

        if action == "tap":
            await self.action.tap(int(item["x"]), int(item["y"]), pause=pause)
            return
        if action == "swipe":
            await self.action.swipe(
                int(item["x1"]),
                int(item["y1"]),
                int(item["x2"]),
                int(item["y2"]),
                int(item.get("duration") or 350),
            )
            await asyncio.sleep(pause)
            return
        if action == "text":
            await self.action.type_text(str(item.get("text") or ""), pause=pause)
            return
        if action == "key":
            key = str(item.get("key") or "").lower()
            if key == "back":
                await self.action.press_back()
            elif key == "enter":
                await self.action.press_enter()
            elif key == "home" and hasattr(self.action, "press_home"):
                await self.action.press_home()
            else:
                raise RuntimeError(f"Unsupported recorded key: {key}")
            await asyncio.sleep(pause)
            return
        if action == "wait":
            await asyncio.sleep(float(item.get("seconds") or pause or 1.0))
            return
        raise RuntimeError(f"Unsupported recorded action: {action}")

    @staticmethod
    def _refuse_risky_purchase_replay(actions: list[dict[str, Any]]) -> None:
        for item in actions:
            haystack = " ".join(str(item.get(key, "")) for key in ("label", "text", "note")).lower()
            if any(word in haystack for word in RISKY_REPLAY_WORDS):
                raise RuntimeError(
                    "Refusing recorded purchase replay with risky buy/pay/confirm labels"
                )
