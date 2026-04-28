"""Generate normalized ROI zones from strategy, analysis, and element boxes."""
from __future__ import annotations

from typing import Any

from core.autobuilder.profile_generator import _default_zones
from core.autobuilder.util import normalized_box, slugify


def generate_roi_zones(
    *,
    strategy: str,
    screen_width: int = 0,
    screen_height: int = 0,
    analysis: dict[str, Any] | None = None,
    labels: list[dict[str, Any]] | None = None,
) -> dict[str, list[float]]:
    zones = _default_zones(strategy)
    for item in list(labels or []):
        name = slugify(str(item.get("name") or item.get("label_id") or "manual_roi"), "manual_roi")
        box = item.get("normalized_box") or item.get("normalizedBox")
        if box:
            zones[name] = normalized_box(box)
    analysis = analysis or {}
    for element in analysis.get("safe_elements", []) if isinstance(analysis.get("safe_elements"), list) else []:
        roi = slugify(str(element.get("roi") or element.get("name") or ""), "element_roi")
        box = element.get("normalized_box") or element.get("normalizedBox")
        if box:
            zones[roi] = normalized_box(box)
            continue
        bbox = element.get("bbox")
        if bbox and screen_width > 0 and screen_height > 0:
            x1, y1, x2, y2 = (float(part) for part in bbox)
            zones[roi] = normalized_box([x1 / screen_width, y1 / screen_height, x2 / screen_width, y2 / screen_height])
    return _merge_clamped(zones)


def _merge_clamped(zones: dict[str, list[float]]) -> dict[str, list[float]]:
    result = {}
    for name, box in zones.items():
        result[name] = normalized_box(box)
    return dict(sorted(result.items()))
