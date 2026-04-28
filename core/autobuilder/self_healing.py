"""Self-healing engine for safe autopilot patch generation."""
from __future__ import annotations

from typing import Any

from core.autobuilder.budgets import BudgetCounter
from core.autobuilder.patches import AutopilotPatch
from core.autobuilder.safety_policy import SafetyPolicy


class SelfHealingEngine:
    def __init__(self, *, policy: SafetyPolicy, budget_counter: BudgetCounter | None = None):
        self.policy = policy
        self.budget_counter = budget_counter

    def propose_patch(self, failure: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
        if self.budget_counter:
            self.budget_counter.consume("max_repair_attempts_per_run")
        if bool(failure.get("fast_gameplay")):
            return {"status": "blocked", "reason": "LLM repair is forbidden inside fast gameplay", "patches": []}
        patches: list[AutopilotPatch] = []
        for element in analysis.get("safe_elements", []):
            if not isinstance(element, dict):
                continue
            decision = self.policy.check_action(element)
            risky = decision.required_review or not decision.allowed
            if element.get("bbox"):
                patches.append(
                    AutopilotPatch(
                        type="add_template",
                        payload={
                            "template_id": element.get("name", "template"),
                            "bbox": element.get("bbox"),
                            "roi": element.get("roi", ""),
                        },
                        requires_review=risky,
                        reason=decision.reason,
                    )
                )
            elif element.get("roi") and element.get("normalized_box"):
                patches.append(
                    AutopilotPatch(
                        type="add_roi",
                        payload={"roi": element["roi"], "normalized_box": element["normalized_box"]},
                        requires_review=risky,
                        reason=decision.reason,
                    )
                )
        if not patches and analysis.get("screen_type"):
            patches.append(
                AutopilotPatch(
                    type="add_screen",
                    payload={"screen_type": analysis["screen_type"], "summary": analysis.get("summary", "")},
                    requires_review=False,
                )
            )
        return {
            "status": "pending_review" if any(p.requires_review for p in patches) else "safe_patch_ready",
            "patches": [patch.to_dict() for patch in patches],
        }
