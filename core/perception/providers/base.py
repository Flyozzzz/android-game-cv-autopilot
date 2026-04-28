"""Provider contract for element detection backends."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from core.frame_source import Frame
from core.perception.element import ElementCandidate
from core.perception.roi import PixelBox


@dataclass(frozen=True)
class ProviderContext:
    frame: Frame
    goal: str
    roi: PixelBox | None = None
    screen_id: str = ""
    profile_id: str = ""


class ElementProvider(Protocol):
    name: str

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        ...
