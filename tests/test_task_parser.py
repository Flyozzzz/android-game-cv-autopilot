from core.autobuilder.task_parser import parse_goal_prompt


def test_task_parser_detects_runner_profile_and_restrictions():
    goal = parse_goal_prompt(
        "Создай автопилот для Subway Surfers. Start a run and survive 60 seconds. No purchases, no login, no multiplayer."
    )

    assert goal.app_name == "Subway Surfers"
    assert goal.package
    assert goal.runtime_strategy == "runner"
    assert "purchase" in goal.forbidden_actions
    assert "login" in goal.forbidden_actions
    assert "multiplayer" in goal.forbidden_actions


def test_task_parser_detects_match3_and_budget_overrides():
    goal = parse_goal_prompt("Create app: Candy Crush. match-3 swap automation. max_build_steps=7 max_runtime_minutes=1")

    assert goal.runtime_strategy == "match3"
    assert goal.budgets.max_build_steps == 7
    assert goal.budgets.max_runtime_minutes == 1
