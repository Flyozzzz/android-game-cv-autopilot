from core.autobuilder.bundle import load_autopilot_bundle, save_autopilot_bundle
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.screen_graph import ScreenGraph


def test_autopilot_bundle_saves_and_loads_validated_artifacts(tmp_path):
    goal = GoalSpec(app_name="Game", goal="open", runtime_strategy="menu", package="com.game")
    graph = ScreenGraph()
    graph.add_screen(screen_id="main", screen_hash="abc")
    profile = {
        "app_name": "Game",
        "package": "com.game",
        "strategy": "menu",
        "screen_zones": {},
        "runtime": {},
    }
    scenario = {"name": "game_scenario", "steps": [{"type": "launch_app"}]}

    result = save_autopilot_bundle(
        root=tmp_path,
        goal=goal,
        safety_policy=SafetyPolicy.from_goal(goal),
        profile=profile,
        scenario=scenario,
        screen_graph=graph,
        reports={"status": "ok"},
    )
    loaded = load_autopilot_bundle(result["bundle_dir"])

    assert loaded["autopilot"]["name"] == "game_autopilot"
    assert loaded["profile"]["package"] == "com.game"
    assert loaded["screen_graph"]["screens"][0]["screen_id"] == "main"
