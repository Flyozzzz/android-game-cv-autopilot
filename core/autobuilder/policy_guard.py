"""Policy guard wrapper used by builder, runners, and dashboard actions."""
from __future__ import annotations

from core.autobuilder.safety_policy import SafetyDecision, SafetyPolicy


class PolicyGuard:
    def __init__(self, policy: SafetyPolicy):
        self.policy = policy

    def check(self, action: dict | str) -> SafetyDecision:
        return self.policy.check_action(action)

    def require_allowed(self, action: dict | str, *, allow_review: bool = False) -> SafetyDecision:
        decision = self.check(action)
        if not decision.allowed:
            raise RuntimeError(decision.reason)
        if decision.required_review and not allow_review:
            raise RuntimeError(decision.reason)
        return decision
