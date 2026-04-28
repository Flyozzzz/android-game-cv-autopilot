"""Generate policy-checked automation scenarios from graph/profile/goal."""
from __future__ import annotations

from typing import Any

from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.schemas import validate_schema


def generate_scenario(goal: GoalSpec, profile: dict[str, Any], screen_graph: Any, policy: SafetyPolicy) -> dict[str, Any]:
    steps: list[dict[str, Any]] = [
        {"type": "launch_app", "package": goal.package or profile.get("package", "")},
        {"type": "wait_until_stable"},
    ]
    if goal.runtime_strategy == "runner":
        steps += [
            {"type": "tap_goal", "goal": "play_button"},
            {"type": "handle_optional_popup", "goal": "close_or_skip"},
            {"type": "enter_fast_gameplay", "plugin": "runner", "duration_sec": goal.budgets.max_runtime_minutes * 60},
        ]
    elif goal.runtime_strategy == "match3":
        steps += [
            {"type": "tap_goal", "goal": "play_button"},
            {"type": "wait_until_stable"},
            {"type": "enter_match3_solver", "plugin": "match3", "max_moves": 12},
        ]
    else:
        steps += [
            {"type": "accept_permissions_if_safe"},
            {"type": "skip_intro_if_present"},
            {"type": "open_main_screen"},
            {"type": "verify_goal_reached"},
        ]
    steps.append({"type": "stop_and_report"})
    for step in steps:
        decision = policy.check_action(step)
        if not decision.allowed:
            raise RuntimeError(f"scenario step blocked: {decision.reason}")
        if decision.required_review:
            step["requires_review"] = True
            step["policy_reason"] = decision.reason
    scenario = {"name": f"{goal.autopilot_id}_scenario", "steps": steps}
    validate_schema("scenario", scenario)
    return scenario
