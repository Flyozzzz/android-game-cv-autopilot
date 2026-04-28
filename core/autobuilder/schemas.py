"""Explicit schema validation for generated autopilot artifacts."""
from __future__ import annotations

from typing import Any


SCHEMAS: dict[str, dict[str, type | tuple[type, ...]]] = {
    "goal_spec": {
        "app_name": str,
        "goal": str,
        "mode": str,
        "allowed_actions": list,
        "forbidden_actions": list,
        "runtime_strategy": str,
        "budgets": dict,
        "requires_human_review": bool,
    },
    "safety_policy": {
        "allowed_scope": list,
        "forbidden_actions": list,
        "review_required_actions": list,
        "allow_network_downloads": bool,
    },
    "screen_graph": {"screens": list, "transitions": list},
    "screen_analysis": {
        "screen_type": str,
        "summary": str,
        "safe_elements": list,
        "risky_elements": list,
        "next_best_goal": str,
    },
    "profile": {
        "app_name": str,
        "package": str,
        "strategy": str,
        "screen_zones": dict,
        "runtime": dict,
    },
    "scenario": {"name": str, "steps": list},
    "bundle": {
        "name": str,
        "version": str,
        "created_by": str,
        "app_name": str,
        "strategy": str,
        "profile_path": str,
        "scenario_path": str,
        "screen_graph_path": str,
        "safety_policy_path": str,
    },
    "patch": {"type": str, "requires_review": bool},
    "eval_report": {
        "success_rate": (int, float),
        "avg_loop_ms": (int, float),
        "llm_calls_per_run": (int, float),
        "forbidden_actions_count": int,
    },
    "run_report": {"status": str, "steps": list, "failures": list, "metrics": dict},
}


class SchemaValidationError(ValueError):
    pass


def validate_schema(kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    if kind not in SCHEMAS:
        raise SchemaValidationError(f"unknown schema: {kind}")
    if not isinstance(payload, dict):
        raise SchemaValidationError(f"{kind} must be an object")
    for key, expected_type in SCHEMAS[kind].items():
        if key not in payload:
            raise SchemaValidationError(f"{kind} missing required key: {key}")
        if not isinstance(payload[key], expected_type):
            raise SchemaValidationError(
                f"{kind}.{key} must be {expected_type}, got {type(payload[key]).__name__}"
            )
    return payload


def validate_many(items: dict[str, dict[str, Any]]) -> None:
    for kind, payload in items.items():
        validate_schema(kind, payload)
