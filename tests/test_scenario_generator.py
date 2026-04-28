from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.scenario_generator import generate_scenario
from core.autobuilder.screen_graph import ScreenGraph


def test_scenario_generator_creates_runner_fast_gameplay_step():
    goal = GoalSpec(app_name="Runner", goal="survive", runtime_strategy="runner", package="com.runner")
    scenario = generate_scenario(goal, {"package": "com.runner"}, ScreenGraph(), SafetyPolicy.from_goal(goal))

    assert scenario["name"] == "runner_scenario"
    assert any(step["type"] == "enter_fast_gameplay" and step["plugin"] == "runner" for step in scenario["steps"])


def test_scenario_generator_marks_review_gated_steps():
    goal = GoalSpec(app_name="App", goal="onboarding", runtime_strategy="generic_app")
    scenario = generate_scenario(goal, {"package": "com.app"}, ScreenGraph(), SafetyPolicy.from_goal(goal))

    permission_steps = [step for step in scenario["steps"] if step["type"] == "accept_permissions_if_safe"]
    assert permission_steps[0]["requires_review"] is True
