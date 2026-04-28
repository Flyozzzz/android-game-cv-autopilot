from core.autobuilder.budgets import BudgetCounter, BuilderBudgets
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.self_healing import SelfHealingEngine


def test_self_healing_generates_safe_template_patch():
    engine = SelfHealingEngine(policy=SafetyPolicy(), budget_counter=BudgetCounter(BuilderBudgets()))

    result = engine.propose_patch(
        {"expected": "continue", "actual": "missing"},
        {"safe_elements": [{"name": "continue_button", "bbox": [1, 2, 30, 40], "roi": "bottom_buttons"}]},
    )

    assert result["status"] == "safe_patch_ready"
    assert result["patches"][0]["type"] == "add_template"


def test_self_healing_blocks_fast_gameplay_repair():
    result = SelfHealingEngine(policy=SafetyPolicy()).propose_patch({"fast_gameplay": True}, {})

    assert result["status"] == "blocked"
    assert result["patches"] == []
