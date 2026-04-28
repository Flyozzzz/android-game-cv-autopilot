from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.profile_generator import generate_profile
from core.autobuilder.screen_graph import ScreenGraph


def test_profile_generator_creates_strategy_defaults_before_roi_generator():
    goal = GoalSpec(app_name="Subway Surfers", goal="survive", runtime_strategy="runner", package="com.game")
    profile = generate_profile(goal, ScreenGraph(), {"summary": "runner game"})

    assert profile["app_name"] == "Subway Surfers"
    assert profile["package"] == "com.game"
    assert profile["strategy"] == "runner"
    assert "runner_lanes" in profile["screen_zones"]
    assert profile["runtime"]["fast_gameplay"] == "local_only"
