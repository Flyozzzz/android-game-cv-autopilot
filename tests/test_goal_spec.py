from core.autobuilder.budgets import BuilderBudgets
from core.autobuilder.goal_spec import GoalSpec


def test_goal_spec_normalizes_mode_strategy_and_autopilot_id():
    goal = GoalSpec(
        app_name="Subway Surfers",
        goal="start a run",
        mode="bad",
        runtime_strategy="bad",
        allowed_actions=["tap", "tap", ""],
        budgets=BuilderBudgets(max_build_steps=12),
    )

    assert goal.mode == "create"
    assert goal.runtime_strategy == "generic_app"
    assert goal.allowed_actions == ["tap"]
    assert goal.autopilot_id == "subway-surfers"
    assert goal.to_dict()["budgets"]["max_build_steps"] == 12


def test_goal_spec_from_mapping_validates_schema_shape():
    goal = GoalSpec.from_mapping({
        "appName": "Candy Crush",
        "goal": "solve a board",
        "mode": "validate",
        "runtimeStrategy": "match3",
        "budgets": {"max_runtime_minutes": 2},
    })

    payload = goal.to_dict()
    assert payload["app_name"] == "Candy Crush"
    assert payload["mode"] == "validate"
    assert payload["runtime_strategy"] == "match3"
    assert payload["budgets"]["max_runtime_minutes"] == 2
