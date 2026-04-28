"""Autopilot bundle save/load helpers."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.autobuilder.artifact_store import ArtifactStore
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.schemas import validate_schema
from core.autobuilder.screen_graph import ScreenGraph


def save_autopilot_bundle(
    *,
    root: str | Path,
    goal: GoalSpec,
    safety_policy: SafetyPolicy,
    profile: dict[str, Any],
    scenario: dict[str, Any],
    screen_graph: ScreenGraph,
    reports: dict[str, Any] | None = None,
) -> dict[str, Any]:
    bundle_dir = Path(root) / goal.autopilot_id
    store = ArtifactStore(bundle_dir)
    store.write_json("profile.json", profile, schema="profile")
    store.write_json("scenario.json", scenario, schema="scenario")
    store.write_json("screen_graph.json", screen_graph.to_dict(), schema="screen_graph")
    store.write_json("safety_policy.json", safety_policy.to_dict(), schema="safety_policy")
    if reports:
        store.write_json("reports/build_report.json", reports)
    autopilot = {
        "name": f"{goal.autopilot_id}_autopilot",
        "version": "0.1.0",
        "created_by": "llm_autopilot_builder",
        "app_name": goal.app_name,
        "strategy": goal.runtime_strategy,
        "profile_path": "profile.json",
        "scenario_path": "scenario.json",
        "screen_graph_path": "screen_graph.json",
        "safety_policy_path": "safety_policy.json",
    }
    validate_schema("bundle", autopilot)
    store.write_json("autopilot.json", autopilot, schema="bundle")
    return {"bundle_dir": str(bundle_dir), "autopilot": autopilot}


def load_autopilot_bundle(path: str | Path) -> dict[str, Any]:
    store = ArtifactStore(path)
    autopilot = store.read_json("autopilot.json", schema="bundle")
    return {
        "autopilot": autopilot,
        "profile": store.read_json(autopilot["profile_path"], schema="profile"),
        "scenario": store.read_json(autopilot["scenario_path"], schema="scenario"),
        "screen_graph": store.read_json(autopilot["screen_graph_path"], schema="screen_graph"),
        "safety_policy": store.read_json(autopilot["safety_policy_path"], schema="safety_policy"),
    }
