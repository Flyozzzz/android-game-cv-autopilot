import pytest

from core.autobuilder.schemas import SchemaValidationError, validate_schema


def test_autobuilder_schemas_accept_required_artifacts():
    validate_schema("screen_analysis", {
        "screen_type": "menu",
        "summary": "main menu",
        "safe_elements": [],
        "risky_elements": [],
        "next_best_goal": "tap_play",
    })
    validate_schema("eval_report", {
        "success_rate": 1.0,
        "avg_loop_ms": 0.0,
        "llm_calls_per_run": 0.0,
        "forbidden_actions_count": 0,
    })


def test_autobuilder_schemas_reject_missing_keys():
    with pytest.raises(SchemaValidationError):
        validate_schema("goal_spec", {"app_name": "x"})
