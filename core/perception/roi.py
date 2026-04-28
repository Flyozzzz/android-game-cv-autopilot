"""Region-of-interest helpers for profile-defined screen zones."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from core.game_profiles import GameProfile, ScreenZone


PixelBox = tuple[int, int, int, int]


@dataclass(frozen=True)
class ROI:
    name: str
    normalized_box: ScreenZone
    pixel_box: PixelBox


def validate_normalized_box(box: ScreenZone) -> ScreenZone:
    if len(box) != 4:
        raise ValueError("ROI box must contain four values")
    x1, y1, x2, y2 = (float(part) for part in box)
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError("ROI coordinates must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1")
    return (x1, y1, x2, y2)


def normalized_to_pixels(box: ScreenZone, *, width: int, height: int) -> PixelBox:
    if width <= 0 or height <= 0:
        raise ValueError("Screen width and height must be positive")
    x1, y1, x2, y2 = validate_normalized_box(box)
    px1 = int(round(x1 * width))
    py1 = int(round(y1 * height))
    px2 = int(round(x2 * width))
    py2 = int(round(y2 * height))
    return (
        max(0, min(width - 1, px1)),
        max(0, min(height - 1, py1)),
        max(1, min(width, px2)),
        max(1, min(height, py2)),
    )


class ROISelector:
    """Resolve named profile zones into pixel-space ROIs."""

    def __init__(self, profile_or_zones: GameProfile | Mapping[str, ScreenZone]):
        if isinstance(profile_or_zones, GameProfile):
            self.zones = dict(profile_or_zones.screen_zones)
        else:
            self.zones = dict(profile_or_zones)

    def resolve(
        self,
        name: str,
        *,
        width: int,
        height: int,
        fallback_full_screen: bool = True,
    ) -> ROI:
        box = self.zones.get(name)
        if box is None:
            if not fallback_full_screen:
                raise KeyError(f"Unknown ROI zone: {name}")
            box = (0.0, 0.0, 1.0, 1.0)
        normalized = validate_normalized_box(box)
        return ROI(
            name=name if name in self.zones else "full_screen",
            normalized_box=normalized,
            pixel_box=normalized_to_pixels(normalized, width=width, height=height),
        )

    def all(self, *, width: int, height: int) -> list[ROI]:
        return [
            ROI(
                name=name,
                normalized_box=validate_normalized_box(box),
                pixel_box=normalized_to_pixels(box, width=width, height=height),
            )
            for name, box in sorted(self.zones.items())
        ]
