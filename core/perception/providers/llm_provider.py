"""Vision LLM provider adapter for ElementFinder fallback mode."""
from __future__ import annotations

from typing import Any

from core.cv_engine import CVEngine
from core.perception.element import ElementCandidate
from core.perception.providers.base import ProviderContext
from core.perception.roi import PixelBox


class LLMProvider:
    name = "llm"

    def __init__(self, cv: Any | None = None):
        self.cv = cv or CVEngine()

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        if not context.frame.png_bytes:
            return []
        element = await self.cv.find_element(context.frame.png_bytes, context.goal)
        if not element:
            return []
        bbox = _bbox_from_ui_element(element)
        if context.roi and not _point_in_roi((int(element.x), int(element.y)), context.roi):
            return []
        return [
            ElementCandidate(
                name=element.name,
                bbox=bbox,
                center=(int(element.x), int(element.y)),
                confidence=max(0.0, min(1.0, float(element.confidence))),
                source=self.name,
                text=element.text,
                screen_id=context.screen_id or None,
            )
        ]


def _bbox_from_ui_element(element: Any) -> tuple[int, int, int, int]:
    width = max(1, int(getattr(element, "width", 50) or 50))
    height = max(1, int(getattr(element, "height", 50) or 50))
    x = int(getattr(element, "x", 0) or 0)
    y = int(getattr(element, "y", 0) or 0)
    return (
        max(0, int(x - width / 2)),
        max(0, int(y - height / 2)),
        int(x + width / 2),
        int(y + height / 2),
    )


def _point_in_roi(point: tuple[int, int], roi: PixelBox) -> bool:
    x, y = point
    x1, y1, x2, y2 = roi
    return x1 <= x <= x2 and y1 <= y <= y2
