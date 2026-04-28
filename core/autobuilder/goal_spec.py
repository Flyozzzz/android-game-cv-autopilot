"""Goal specification produced from a user autopilot-builder prompt."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from core.autobuilder.budgets import BuilderBudgets
from core.autobuilder.schemas import validate_schema
from core.autobuilder.util import clean_list, slugify


BUILDER_MODES = {"create", "improve", "repair", "validate", "shadow"}
RUNTIME_STRATEGIES = {"menu", "runner", "match3", "generic_app"}


@dataclass(frozen=True)
class GoalSpec:
    app_name: str
    goal: str
    mode: str = "create"
    allowed_actions: list[str] = field(default_factory=lambda: ["launch", "tap", "swipe", "wait", "analyze"])
    forbidden_actions: list[str] = field(default_factory=lambda: ["purchase", "real_login", "subscribe", "bypass_anticheat"])
    runtime_strategy: str = "generic_app"
    budgets: BuilderBudgets = field(default_factory=BuilderBudgets)
    requires_human_review: bool = True
    package: str = ""
    autopilot_id: str = ""

    def __post_init__(self) -> None:
        mode = self.mode if self.mode in BUILDER_MODES else "create"
        strategy = self.runtime_strategy if self.runtime_strategy in RUNTIME_STRATEGIES else "generic_app"
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "runtime_strategy", strategy)
        object.__setattr__(self, "allowed_actions", clean_list(self.allowed_actions))
        object.__setattr__(self, "forbidden_actions", clean_list(self.forbidden_actions))
        if not self.autopilot_id:
            object.__setattr__(self, "autopilot_id", slugify(self.app_name, "autopilot"))

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["budgets"] = self.budgets.to_dict()
        validate_schema("goal_spec", data)
        return data

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "GoalSpec":
        budgets = data.get("budgets")
        return cls(
            app_name=str(data.get("app_name") or data.get("appName") or "Unknown App"),
            goal=str(data.get("goal") or ""),
            mode=str(data.get("mode") or "create").lower(),
            allowed_actions=clean_list(data.get("allowed_actions") or data.get("allowedActions")),
            forbidden_actions=clean_list(data.get("forbidden_actions") or data.get("forbiddenActions")),
            runtime_strategy=str(data.get("runtime_strategy") or data.get("runtimeStrategy") or "generic_app"),
            budgets=budgets if isinstance(budgets, BuilderBudgets) else BuilderBudgets.from_mapping(budgets),
            requires_human_review=bool(data.get("requires_human_review", data.get("requiresHumanReview", True))),
            package=str(data.get("package") or ""),
            autopilot_id=str(data.get("autopilot_id") or data.get("autopilotId") or ""),
        )
