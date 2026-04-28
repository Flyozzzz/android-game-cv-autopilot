"""Common element candidate model for local-first perception providers."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class ElementCandidate:
    name: str
    bbox: tuple[int, int, int, int]
    center: tuple[int, int]
    confidence: float
    source: str
    text: str | None = None
    screen_id: str | None = None
    latency_ms: float = 0.0

    @classmethod
    def from_bbox(
        cls,
        *,
        name: str,
        bbox: tuple[int, int, int, int],
        confidence: float,
        source: str,
        text: str | None = None,
        screen_id: str | None = None,
        latency_ms: float = 0.0,
    ) -> "ElementCandidate":
        x1, y1, x2, y2 = bbox
        return cls(
            name=name,
            bbox=bbox,
            center=(int((x1 + x2) / 2), int((y1 + y2) / 2)),
            confidence=max(0.0, min(1.0, float(confidence))),
            source=source,
            text=text,
            screen_id=screen_id,
            latency_ms=latency_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
