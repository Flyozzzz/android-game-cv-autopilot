from core.autobuilder.context import BuildContext
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy


def test_build_context_is_explicitly_updated():
    goal = GoalSpec(app_name="Game", goal="open menu")
    context = BuildContext.create(goal, SafetyPolicy.from_goal(goal))

    updated = context.with_updates(metrics={"loop_total_ms": 12})

    assert context.metrics == {}
    assert updated.metrics["loop_total_ms"] == 12
    assert updated.run_id == context.run_id
