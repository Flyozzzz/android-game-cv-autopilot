"""Lightweight local detector for lane-runner games.

This is intentionally not an LLM/CV planner. Runner games need sub-second
gestures, so this module makes a cheap screenshot-based decision that can run in
a tight loop. It is a generic fallback, not a per-game optimal bot.
"""
from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Literal

from PIL import Image, ImageStat


RunnerGesture = Literal["left", "right", "up", "down", "none"]


@dataclass(frozen=True)
class FastRunnerDecision:
    gesture: RunnerGesture
    reason: str
    lane_scores: tuple[float, float, float]


class FastRunnerDetector:
    """Detect coarse obstacles in the lower lanes of portrait runner games."""

    def __init__(self, obstacle_threshold: float = 42.0):
        self.obstacle_threshold = obstacle_threshold

    def decide(self, screenshot_png: bytes) -> FastRunnerDecision:
        image = Image.open(BytesIO(screenshot_png)).convert("RGB")
        return self.decide_image(image)

    def decide_image(self, image: Image.Image) -> FastRunnerDecision:
        image = image.convert("RGB")
        width, height = image.size
        if width <= 0 or height <= 0:
            return FastRunnerDecision("none", "empty image", (0.0, 0.0, 0.0))

        # Runner lanes sit in the lower half. Avoid the bottom nav/gesture bar.
        y1 = int(height * 0.58)
        y2 = int(height * 0.86)
        x_pad = int(width * 0.10)
        lane_width = (width - 2 * x_pad) // 3
        lanes = []
        for i in range(3):
            lx1 = x_pad + i * lane_width
            lx2 = x_pad + (i + 1) * lane_width
            lanes.append((lx1, y1, lx2, y2))

        scores = tuple(self._obstacle_score(image.crop(box)) for box in lanes)
        left, center, right = scores
        center_blocked = center >= self.obstacle_threshold

        if not center_blocked:
            return FastRunnerDecision("none", "center lane clear", scores)

        if left + 6 < right:
            return FastRunnerDecision("left", "center blocked, left lane clearer", scores)
        if right + 6 < left:
            return FastRunnerDecision("right", "center blocked, right lane clearer", scores)
        return FastRunnerDecision("up", "center blocked, side lanes unclear", scores)

    @staticmethod
    def _obstacle_score(crop: Image.Image) -> float:
        gray = crop.convert("L").resize((24, 32))
        stat = ImageStat.Stat(gray)
        mean = float(stat.mean[0])
        stddev = float(stat.stddev[0])
        hist = gray.histogram()
        total = max(1, sum(hist))
        dark_ratio = sum(hist[:70]) / total
        bright_ratio = sum(hist[205:]) / total
        contrast = stddev * 1.35
        # Obstacles tend to create local contrast and non-background dark/bright
        # blobs. The ratios keep the score useful across different maps.
        return contrast + dark_ratio * 40.0 + bright_ratio * 12.0 + max(0.0, 128.0 - mean) * 0.08
