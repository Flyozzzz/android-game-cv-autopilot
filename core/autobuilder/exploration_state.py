"""Exploration state emitted by the safe Explorer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExplorationStep:
    index: int
    screen_id: str
    action: dict[str, Any]
    result_screen_id: str
    policy_result: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ExplorationState:
    status: str
    steps: list[ExplorationStep] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    screenshots: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "steps": [step.to_dict() for step in self.steps],
            "failures": list(self.failures),
            "screenshots": list(self.screenshots),
        }
