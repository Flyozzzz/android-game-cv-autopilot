"""Detect whether recent screen frames are stable enough for actions."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from io import BytesIO
import time
from typing import Any

from PIL import Image, ImageChops, ImageStat

from core.frame_source import Frame
from core.perception.roi import PixelBox


@dataclass(frozen=True)
class StabilityResult:
    stable: bool
    reason: str
    frames_observed: int
    mean_diff: float
    threshold: float


class ScreenStabilityDetector:
    """Compare recent frames at low resolution to avoid acting mid-transition."""

    def __init__(
        self,
        *,
        window_size: int = 3,
        diff_threshold: float = 2.5,
        resize: tuple[int, int] = (64, 64),
    ):
        self.window_size = max(2, int(window_size or 2))
        self.diff_threshold = max(0.0, float(diff_threshold))
        self.resize = resize
        self._frames: list[Image.Image] = []

    def reset(self) -> None:
        self._frames.clear()

    def observe(self, frame: Frame | bytes, *, roi: PixelBox | None = None) -> StabilityResult:
        image = self._prepare(frame, roi=roi)
        self._frames.append(image)
        del self._frames[:-self.window_size]
        if len(self._frames) < self.window_size:
            return StabilityResult(
                stable=False,
                reason="warming_up",
                frames_observed=len(self._frames),
                mean_diff=0.0,
                threshold=self.diff_threshold,
            )
        diffs = [
            self._mean_abs_diff(previous, current)
            for previous, current in zip(self._frames, self._frames[1:])
        ]
        mean_diff = round(sum(diffs) / len(diffs), 3)
        stable = mean_diff <= self.diff_threshold
        return StabilityResult(
            stable=stable,
            reason="stable" if stable else "changing",
            frames_observed=len(self._frames),
            mean_diff=mean_diff,
            threshold=self.diff_threshold,
        )

    def _prepare(self, frame: Frame | bytes, *, roi: PixelBox | None) -> Image.Image:
        png = frame.png_bytes if isinstance(frame, Frame) else frame
        if not png:
            raise RuntimeError("Screen stability requires PNG frame bytes")
        image = Image.open(BytesIO(png)).convert("L")
        if roi is not None:
            image = image.crop(_clamped_roi(roi, image.size))
        return image.resize(self.resize)

    @staticmethod
    def _mean_abs_diff(previous: Image.Image, current: Image.Image) -> float:
        diff = ImageChops.difference(previous, current)
        return float(ImageStat.Stat(diff).mean[0])


async def wait_until_stable(
    frame_source: Any,
    *,
    detector: ScreenStabilityDetector | None = None,
    timeout_ms: int = 1500,
    poll_interval_ms: int = 80,
    roi: PixelBox | None = None,
) -> StabilityResult:
    detector = detector or ScreenStabilityDetector()
    deadline = time.monotonic() + max(1, timeout_ms) / 1000.0
    last_result = StabilityResult(False, "not_started", 0, 0.0, detector.diff_threshold)
    while time.monotonic() <= deadline:
        frame = await frame_source.latest_frame()
        last_result = detector.observe(frame, roi=roi)
        if last_result.stable:
            return last_result
        await asyncio.sleep(max(0, poll_interval_ms) / 1000.0)
    return StabilityResult(
        stable=False,
        reason="timeout",
        frames_observed=last_result.frames_observed,
        mean_diff=last_result.mean_diff,
        threshold=last_result.threshold,
    )


def _clamped_roi(roi: PixelBox, size: tuple[int, int]) -> PixelBox:
    width, height = size
    x1, y1, x2, y2 = roi
    return (
        max(0, min(width - 1, int(x1))),
        max(0, min(height - 1, int(y1))),
        max(1, min(width, int(x2))),
        max(1, min(height, int(y2))),
    )
