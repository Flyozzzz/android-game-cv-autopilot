"""Candidate ranking for local-first perception providers."""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from core.perception.element import ElementCandidate
from core.perception.roi import PixelBox


@dataclass(frozen=True)
class RankedCandidate:
    candidate: ElementCandidate
    score: float
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class FusionConfig:
    roi_bonus: float = 0.08
    text_match_bonus: float = 0.18
    profile_priority_bonus: float = 0.08
    recency_bonus: float = 0.04
    stale_frame_penalty: float = 0.0
    source_priorities: dict[str, float] = field(default_factory=dict)


class FusionEngine:
    def __init__(self, config: FusionConfig | None = None):
        self.config = config or FusionConfig()

    def rank(
        self,
        candidates: list[ElementCandidate],
        *,
        goal: str = "",
        roi: PixelBox | None = None,
        recent_screen_ids: set[str] | None = None,
    ) -> list[RankedCandidate]:
        ranked = [
            self.score_candidate(
                candidate,
                goal=goal,
                roi=roi,
                recent_screen_ids=recent_screen_ids or set(),
            )
            for candidate in candidates
        ]
        return sorted(ranked, key=lambda item: item.score, reverse=True)

    def score_candidate(
        self,
        candidate: ElementCandidate,
        *,
        goal: str = "",
        roi: PixelBox | None = None,
        recent_screen_ids: set[str] | None = None,
    ) -> RankedCandidate:
        score = float(candidate.confidence)
        reasons: list[str] = [f"confidence:{candidate.confidence:.3f}"]
        if roi and _point_in_box(candidate.center, roi):
            score += self.config.roi_bonus
            reasons.append("roi")
        if _text_matches(goal, candidate):
            score += self.config.text_match_bonus
            reasons.append("text")
        priority = self.config.source_priorities.get(candidate.source, 0.0)
        if priority:
            score += priority
            reasons.append(f"source_priority:{candidate.source}")
        if candidate.screen_id and candidate.screen_id in (recent_screen_ids or set()):
            score += self.config.recency_bonus
            reasons.append("recency")
        if self.config.stale_frame_penalty:
            score -= self.config.stale_frame_penalty
            reasons.append("stale_penalty")
        return RankedCandidate(candidate=candidate, score=round(score, 4), reasons=tuple(reasons))


def _point_in_box(point: tuple[int, int], box: PixelBox) -> bool:
    x, y = point
    x1, y1, x2, y2 = box
    return x1 <= x <= x2 and y1 <= y <= y2


def _text_matches(goal: str, candidate: ElementCandidate) -> bool:
    goal_tokens = _tokens(goal)
    if not goal_tokens:
        return False
    haystack = _tokens(" ".join(part for part in (candidate.name, candidate.text or "") if part))
    if not haystack:
        return False
    return bool(goal_tokens & haystack)


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-zа-я0-9]+", value.lower()) if len(token) >= 2}
