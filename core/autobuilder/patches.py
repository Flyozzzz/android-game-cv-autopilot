"""Patch models for self-healing generated autopilots."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.autobuilder.schemas import validate_schema


PATCH_TYPES = {
    "add_template",
    "update_template_threshold",
    "add_roi",
    "update_roi",
    "add_screen",
    "add_transition",
    "update_scenario_step",
    "mark_risky_element",
    "add_blocker_word",
}


@dataclass(frozen=True)
class AutopilotPatch:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    requires_review: bool = False
    reason: str = ""
    status: str = "pending"

    def __post_init__(self) -> None:
        if self.type not in PATCH_TYPES:
            raise ValueError(f"unsupported patch type: {self.type}")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        validate_schema("patch", data)
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "AutopilotPatch":
        return cls(
            type=str(data.get("type") or ""),
            payload=dict(data.get("payload") or {}),
            requires_review=bool(data.get("requires_review", data.get("requiresReview", False))),
            reason=str(data.get("reason") or ""),
            status=str(data.get("status") or "pending"),
        )
