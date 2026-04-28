"""UIAutomator-backed provider for native Android UI text elements."""
from __future__ import annotations

import re
from typing import Any

from core.perception.element import ElementCandidate
from core.perception.providers.base import ProviderContext
from core.perception.roi import PixelBox


class UIAutomatorProvider:
    name = "uiautomator"

    def __init__(self, action: Any, *, default_box: tuple[int, int] = (220, 72)):
        self.action = action
        self.default_box = default_box

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        if not hasattr(self.action, "get_visible_texts"):
            return []
        visible = await self.action.get_visible_texts()
        goal_tokens = _tokens(context.goal)
        candidates: list[ElementCandidate] = []
        for item in visible or ():
            parsed = _parse_visible_text(item)
            if parsed is None:
                continue
            text, cx, cy = parsed
            if context.roi and not _point_in_roi((cx, cy), context.roi):
                continue
            matched = bool(goal_tokens & _tokens(text)) if goal_tokens else True
            if goal_tokens and not matched:
                continue
            width, height = self.default_box
            bbox = (
                max(0, int(cx - width / 2)),
                max(0, int(cy - height / 2)),
                int(cx + width / 2),
                int(cy + height / 2),
            )
            candidates.append(
                ElementCandidate(
                    name=text,
                    bbox=bbox,
                    center=(cx, cy),
                    confidence=0.86 if matched else 0.55,
                    source=self.name,
                    text=text,
                    screen_id=context.screen_id or None,
                )
            )
        return candidates


def _parse_visible_text(item: Any) -> tuple[str, int, int] | None:
    if isinstance(item, dict):
        text = str(item.get("text") or item.get("label") or "").strip()
        cx = item.get("cx", item.get("x"))
        cy = item.get("cy", item.get("y"))
    elif isinstance(item, (list, tuple)) and len(item) >= 3:
        text = str(item[0] or "").strip()
        cx = item[1]
        cy = item[2]
    else:
        return None
    if not text:
        return None
    try:
        return text, int(cx), int(cy)
    except (TypeError, ValueError):
        return None


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-zа-я0-9]+", value.lower()) if len(token) >= 2}


def _point_in_roi(point: tuple[int, int], roi: PixelBox) -> bool:
    x, y = point
    x1, y1, x2, y2 = roi
    return x1 <= x <= x2 and y1 <= y <= y2
