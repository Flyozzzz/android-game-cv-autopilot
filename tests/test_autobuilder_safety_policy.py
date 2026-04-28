import pytest

from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.policy_guard import PolicyGuard
from core.autobuilder.safety_policy import SafetyPolicy


def test_safety_policy_blocks_purchase_and_requires_review_for_install():
    policy = SafetyPolicy.from_goal(GoalSpec(app_name="Game", goal="no purchases"))

    purchase = policy.check_action({"type": "tap", "target": "buy coins"})
    install = policy.check_action({"type": "install_apk", "source": "/tmp/game.apk"})

    assert not purchase.allowed
    assert purchase.required_review
    assert install.allowed
    assert install.required_review


def test_policy_guard_rejects_review_required_actions_by_default():
    guard = PolicyGuard(SafetyPolicy())

    with pytest.raises(RuntimeError, match="Review required"):
        guard.require_allowed({"type": "install_apk", "source": "/tmp/game.apk"})

    decision = guard.require_allowed({"type": "install_apk", "source": "/tmp/game.apk"}, allow_review=True)
    assert decision.required_review
