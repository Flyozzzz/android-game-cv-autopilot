import pytest

from core.autobuilder.budgets import BudgetCounter, BuilderBudgets


def test_builder_budgets_parse_prompt_and_mapping():
    budgets = BuilderBudgets.from_prompt("max_build_steps=22 max_actions_per_screen=3 max_llm_calls_per_build=4")

    assert budgets.max_build_steps == 22
    assert budgets.max_actions_per_screen == 3
    assert budgets.max_llm_calls_per_build == 4
    assert BuilderBudgets.from_mapping({"maxRuntimeMinutes": 2}).max_runtime_minutes == 2


def test_budget_counter_stops_on_exhaustion():
    counter = BudgetCounter(BuilderBudgets(max_llm_calls_per_build=1))

    counter.consume("max_llm_calls_per_build")
    with pytest.raises(RuntimeError, match="budget exhausted"):
        counter.consume("max_llm_calls_per_build")
