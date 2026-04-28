"""Template matching provider for canvas/game UI elements."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageChops, ImageStat

from core.frame_source import frame_to_image
from core.perception.element import ElementCandidate
from core.perception.providers.base import ProviderContext
from core.perception.roi import PixelBox
from core.perception.template_registry import TemplateRegistry, TemplateSpec


@dataclass(frozen=True)
class TemplateMatch:
    bbox: tuple[int, int, int, int]
    confidence: float
    template_path: Path


class TemplateProvider:
    name = "template"

    def __init__(self, registry: TemplateRegistry):
        self.registry = registry

    async def find(self, context: ProviderContext) -> list[ElementCandidate]:
        try:
            screen = frame_to_image(context.frame)
        except RuntimeError:
            return []
        candidates: list[ElementCandidate] = []
        negative_only_ids = {
            negative_id
            for spec in self.registry.all()
            for negative_id in spec.negative_templates
        }
        for spec in self.registry.all():
            if spec.id in negative_only_ids:
                continue
            matches = self._find_for_spec(screen, spec, context.roi)
            for match in matches:
                if self._suppressed_by_negative(screen, spec, context.roi, match.confidence):
                    continue
                x1, y1, x2, y2 = match.bbox
                tx = int(x1 + (x2 - x1) * spec.tap_offset[0])
                ty = int(y1 + (y2 - y1) * spec.tap_offset[1])
                candidates.append(
                    ElementCandidate(
                        name=spec.id,
                        bbox=match.bbox,
                        center=(tx, ty),
                        confidence=match.confidence,
                        source=self.name,
                        text=spec.id.replace("_", " "),
                        screen_id=context.screen_id or None,
                    )
                )
        return candidates

    def _find_for_spec(
        self,
        screen: Image.Image,
        spec: TemplateSpec,
        roi: PixelBox | None,
    ) -> list[TemplateMatch]:
        matches: list[TemplateMatch] = []
        search_image, offset = _crop_roi(screen, roi)
        for path in self.registry.expanded_paths(spec):
            template = Image.open(path).convert("RGB")
            for scale in spec.scales:
                scaled = _scaled_template(template, scale)
                if scaled.width > search_image.width or scaled.height > search_image.height:
                    continue
                match = _best_match(search_image, scaled, step=spec.search_step)
                if match and match.confidence >= spec.threshold:
                    x1, y1, x2, y2 = match.bbox
                    ox, oy = offset
                    matches.append(
                        TemplateMatch(
                            bbox=(x1 + ox, y1 + oy, x2 + ox, y2 + oy),
                            confidence=match.confidence,
                            template_path=path,
                        )
                    )
        return _dedupe_matches(matches)

    def _suppressed_by_negative(
        self,
        screen: Image.Image,
        spec: TemplateSpec,
        roi: PixelBox | None,
        positive_confidence: float,
    ) -> bool:
        if not spec.negative_templates:
            return False
        search_image, _ = _crop_roi(screen, roi)
        for negative_id in spec.negative_templates:
            negative_spec = self.registry.get(negative_id)
            if not negative_spec:
                continue
            for path in self.registry.expanded_paths(negative_spec):
                template = Image.open(path).convert("RGB")
                match = _best_match(search_image, template, step=negative_spec.search_step)
                if match and match.confidence >= min(negative_spec.threshold, positive_confidence):
                    return True
        return False


def _crop_roi(image: Image.Image, roi: PixelBox | None) -> tuple[Image.Image, tuple[int, int]]:
    if roi is None:
        return image, (0, 0)
    x1, y1, x2, y2 = roi
    x1 = max(0, min(image.width - 1, int(x1)))
    y1 = max(0, min(image.height - 1, int(y1)))
    x2 = max(1, min(image.width, int(x2)))
    y2 = max(1, min(image.height, int(y2)))
    return image.crop((x1, y1, x2, y2)), (x1, y1)


def _scaled_template(template: Image.Image, scale: float) -> Image.Image:
    scale = max(0.05, float(scale))
    width = max(1, int(round(template.width * scale)))
    height = max(1, int(round(template.height * scale)))
    if width == template.width and height == template.height:
        return template
    return template.resize((width, height))


def _best_match(screen: Image.Image, template: Image.Image, *, step: int = 1) -> TemplateMatch | None:
    cv2_match = _best_match_cv2(screen, template)
    if cv2_match is not None:
        return cv2_match
    return _best_match_pil(screen, template, step=step)


def _best_match_cv2(screen: Image.Image, template: Image.Image) -> TemplateMatch | None:
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore
    except Exception:
        return None
    # TM_SQDIFF_NORMED is unreliable for flat templates and can return a bogus
    # zero-confidence match. Let the deterministic PIL matcher handle those.
    if float(ImageStat.Stat(template.convert("L")).stddev[0]) < 1e-6:
        return None
    screen_arr = cv2.cvtColor(np.array(screen), cv2.COLOR_RGB2BGR)
    template_arr = cv2.cvtColor(np.array(template), cv2.COLOR_RGB2BGR)
    result = cv2.matchTemplate(screen_arr, template_arr, cv2.TM_SQDIFF_NORMED)
    min_val, _, min_loc, _ = cv2.minMaxLoc(result)
    x, y = min_loc
    return TemplateMatch(
        bbox=(x, y, x + template.width, y + template.height),
        confidence=round(max(0.0, 1.0 - float(min_val)), 4),
        template_path=Path("cv2"),
    )


def _best_match_pil(screen: Image.Image, template: Image.Image, *, step: int = 1) -> TemplateMatch | None:
    screen_l = screen.convert("L")
    template_l = template.convert("L")
    best: TemplateMatch | None = None
    step = max(1, int(step))
    for y in range(0, screen_l.height - template_l.height + 1, step):
        for x in range(0, screen_l.width - template_l.width + 1, step):
            crop = screen_l.crop((x, y, x + template_l.width, y + template_l.height))
            diff = ImageChops.difference(crop, template_l)
            mean = float(ImageStat.Stat(diff).mean[0])
            confidence = round(max(0.0, 1.0 - mean / 255.0), 4)
            if best is None or confidence > best.confidence:
                best = TemplateMatch(
                    bbox=(x, y, x + template_l.width, y + template_l.height),
                    confidence=confidence,
                    template_path=Path("pil"),
                )
    return best


def _dedupe_matches(matches: Iterable[TemplateMatch]) -> list[TemplateMatch]:
    result: list[TemplateMatch] = []
    for match in sorted(matches, key=lambda item: item.confidence, reverse=True):
        if any(_iou(match.bbox, existing.bbox) > 0.5 for existing in result):
            continue
        result.append(match)
    return result


def _iou(a: tuple[int, int, int, int], b: tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0
