"""Explicit BuildContext passed between autopilot builder modules."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.autobuilder.budgets import BudgetCounter
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.screen_graph import ScreenGraph
from core.metrics import new_run_id


@dataclass(frozen=True)
class BuildContext:
    run_id: str
    goal_spec: GoalSpec
    safety_policy: SafetyPolicy
    app_info: dict[str, Any] = field(default_factory=dict)
    screen_graph: ScreenGraph = field(default_factory=ScreenGraph)
    profile: dict[str, Any] = field(default_factory=dict)
    artifact_paths: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    trace: list[dict[str, Any]] = field(default_factory=list)
    budget_counter: BudgetCounter | None = None

    @classmethod
    def create(cls, goal_spec: GoalSpec, safety_policy: SafetyPolicy) -> "BuildContext":
        return cls(
            run_id=new_run_id(),
            goal_spec=goal_spec,
            safety_policy=safety_policy,
            budget_counter=BudgetCounter(goal_spec.budgets),
        )

    def with_updates(self, **updates: Any) -> "BuildContext":
        data = {
            "run_id": self.run_id,
            "goal_spec": self.goal_spec,
            "safety_policy": self.safety_policy,
            "app_info": self.app_info,
            "screen_graph": self.screen_graph,
            "profile": self.profile,
            "artifact_paths": self.artifact_paths,
            "metrics": self.metrics,
            "trace": self.trace,
            "budget_counter": self.budget_counter,
        }
        data.update(updates)
        return BuildContext(**data)

    def artifact_dir(self, root: str | Path = "autopilots") -> Path:
        return Path(root) / self.goal_spec.autopilot_id
