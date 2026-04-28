import asyncio
from io import BytesIO
import subprocess

import pytest
from PIL import Image

from core.autobuilder import builder as builder_module
from core.autobuilder.app_manager import AppManager, _default_runner, _field, _is_relative_to
from core.autobuilder.budgets import BudgetCounter, BuilderBudgets
from core.autobuilder.context import BuildContext
from core.autobuilder.exploration_state import ExplorationStep
from core.autobuilder.explorer import Explorer
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.live_validation import run_live_validation
from core.autobuilder.patches import AutopilotPatch
from core.autobuilder.policy_guard import PolicyGuard
from core.autobuilder.profile_generator import generate_profile
from core.autobuilder.redaction import redact_obj
from core.autobuilder.redaction import redacted_json
from core.autobuilder.replay_test_runner import run_replay_tests
from core.autobuilder.review import PatchReviewQueue
from core.autobuilder.roi_generator import generate_roi_zones
from core.autobuilder.safety_policy import SafetyPolicy, safety_policy_from_mapping
from core.autobuilder.scenario_generator import generate_scenario
from core.autobuilder.schemas import SchemaValidationError, validate_many, validate_schema
from core.autobuilder.screen_analyst import ScreenAnalyst, _parse_analysis
from core.autobuilder.screen_graph import ScreenGraph
from core.autobuilder.self_healing import SelfHealingEngine
from core.autobuilder.task_parser import _extract_goal, _selector_matches, parse_goal_prompt
from core.autobuilder.template_miner import _valid_bbox, mine_templates
from core.autobuilder.util import clean_list, normalized_box, rel_path, slugify
from core.frame_source import Frame, FrameSource


def _png(width=32, height=32, color="white"):
    image = Image.new("RGB", (width, height), color)
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frame(width=32, height=32, color="white"):
    return Frame(1, width, height, None, _png(width, height, color), "test", 0)


class StaticFrameSource(FrameSource):
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    async def latest_frame(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame


def test_app_manager_edges_and_helpers(tmp_path, monkeypatch):
    class Runner:
        def __init__(self, install_code=0, clear_code=0, launch_code=0):
            self.install_code = install_code
            self.clear_code = clear_code
            self.launch_code = launch_code

        def __call__(self, args, timeout):
            joined = " ".join(args)
            if "monkey" in joined:
                return subprocess.CompletedProcess(args, self.launch_code, stdout=b"", stderr=b"launch failed")
            if "pm path" in joined:
                return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"")
            if "dumpsys package" in joined:
                return subprocess.CompletedProcess(args, 0, stdout=b"versionCode=2\n", stderr=b"")
            if "dumpsys window" in joined:
                return subprocess.CompletedProcess(args, 0, stdout=b"no focus here\n", stderr=b"")
            if "install -r" in joined:
                return subprocess.CompletedProcess(args, self.install_code, stdout=b"", stderr=b"install failed")
            if "pm clear" in joined:
                return subprocess.CompletedProcess(args, self.clear_code, stdout=b"", stderr=b"clear failed")
            if "force-stop" in joined:
                return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"stopped")
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    policy = SafetyPolicy(review_required_actions=[])
    manager = AppManager(runner=Runner(), policy=policy)
    assert manager.get_current_activity() == ""
    assert manager.stop_app("pkg") == {"ok": False, "stderr": "stopped"}
    with pytest.raises(RuntimeError, match="launch failed"):
        AppManager(runner=Runner(launch_code=1), policy=policy).launch_app("pkg")
    with pytest.raises(RuntimeError, match="existing APK"):
        manager.install_apk(tmp_path / "missing.apk")
    apk = tmp_path / "app.apk"
    apk.write_bytes(b"apk")
    with pytest.raises(RuntimeError, match="allowlisted"):
        AppManager(runner=Runner(), policy=policy, trusted_apk_roots=[tmp_path / "trusted"]).install_apk(apk)
    with pytest.raises(RuntimeError, match="install failed"):
        AppManager(runner=Runner(install_code=1), policy=policy).install_apk(apk)
    assert manager.install_apk(apk)["installed"] is True
    with pytest.raises(RuntimeError, match="test devices"):
        AppManager(runner=Runner(), policy=policy, test_device=False).reset_app_data("pkg")
    with pytest.raises(RuntimeError, match="clear failed"):
        AppManager(runner=Runner(clear_code=1), policy=policy).reset_app_data("pkg")
    assert manager.reset_app_data("pkg") == {"reset": True, "package": "pkg"}
    assert _field("abc", "missing=") == ""
    assert _is_relative_to(tmp_path / "a", tmp_path)
    assert not _is_relative_to(tmp_path / "a", tmp_path / "b")
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout=b"ok", stderr=b""))
    assert _default_runner(["adb", "devices"], 1).stdout == b"ok"


def test_budget_schema_util_safety_and_patch_edges(tmp_path):
    budgets = BuilderBudgets.from_prompt("60 seconds max steps 8 depth=2")
    assert budgets.max_build_steps == 8
    assert budgets.max_exploration_depth == 2
    assert BuilderBudgets.from_mapping({"max_build_steps": "bad"}).max_build_steps == 100
    counter = BudgetCounter(BuilderBudgets())
    counter.consume("max_build_steps")
    assert counter.snapshot()["max_build_steps"] == 1
    with pytest.raises(SchemaValidationError):
        validate_schema("unknown", {})
    with pytest.raises(SchemaValidationError):
        validate_schema("goal_spec", "bad")
    with pytest.raises(SchemaValidationError):
        validate_schema("goal_spec", {
            "app_name": "x",
            "goal": "x",
            "mode": "create",
            "allowed_actions": [],
            "forbidden_actions": [],
            "runtime_strategy": "menu",
            "budgets": {},
            "requires_human_review": "yes",
        })
    validate_many({"screen_graph": {"screens": [], "transitions": []}})
    assert slugify("", "fallback") == "fallback"
    assert clean_list("a,b\na") == ["a", "b"]
    assert rel_path(tmp_path / "a", tmp_path) == "a"
    assert rel_path("/not/under/root", tmp_path) == "/not/under/root"
    assert clean_list(7) == ["7"]
    with pytest.raises(ValueError):
        normalized_box([0, 0, 1])
    with pytest.raises(ValueError):
        normalized_box([0.8, 0, 0.2, 1])
    policy = safety_policy_from_mapping({"allowRealLogin": True, "allowNetworkDownloads": True})
    assert policy.check_action({"type": "login"}).allowed
    assert policy.check_action("download https://example.test/app.apk").allowed
    assert SafetyPolicy().check_action("download https://example.test/app.apk").allowed is False
    assert SafetyPolicy().check_action("tap").to_dict()["allowed"] is True
    assert SafetyPolicy().filter_safe_actions([{"type": "tap"}, {"type": "tap", "target": "buy"}]) == [{"type": "tap"}]
    assert PolicyGuard(SafetyPolicy()).require_allowed({"type": "tap"}).allowed
    with pytest.raises(RuntimeError, match="Forbidden action"):
        PolicyGuard(SafetyPolicy()).require_allowed({"target": "buy"})
    with pytest.raises(ValueError):
        AutopilotPatch(type="bad")
    assert AutopilotPatch.from_mapping({"type": "add_screen", "requiresReview": True}).requires_review
    assert redact_obj(("token", {"ok": "yes"})) == ["token", {"ok": "yes"}]
    assert '"ok": "yes"' in redacted_json({"ok": "yes"})
    assert BuildContext.create(GoalSpec(app_name="App", goal="open"), SafetyPolicy()).artifact_dir(tmp_path) == tmp_path / "app"
    assert ExplorationStep(1, "s", {}, "t", "ok").to_dict()["screen_id"] == "s"


def test_explorer_action_and_purchase_edges():
    goal = GoalSpec(app_name="Game", goal="open", budgets=BuilderBudgets(max_exploration_depth=2))
    context = BuildContext.create(goal, SafetyPolicy())
    actions = []

    async def texts():
        return ["Next"]

    async def candidates(_goal):
        return [{"name": "continue_button"}]

    async def execute(action):
        actions.append(action)
        return "executed"

    updated, state = asyncio.run(
        Explorer(
            frame_source=StaticFrameSource([_frame(), _frame()]),
            visible_texts=texts,
            candidate_finder=candidates,
            action_executor=execute,
        ).explore(context)
    )

    assert actions
    assert state.steps[0].policy_result == "executed"
    assert updated.screen_graph.get("screen-001").type == "menu"
    assert updated.screen_graph.outgoing("screen-001")
    async def purchase_texts():
        return ["Buy coins"]
    purchase_base = BuildContext.create(GoalSpec(app_name="Purchase", goal="inspect", budgets=BuilderBudgets(max_exploration_depth=1)), SafetyPolicy())
    purchase_context, _purchase_state = asyncio.run(
        Explorer(frame_source=StaticFrameSource([_frame()]), visible_texts=purchase_texts).explore(purchase_base)
    )
    assert purchase_context.screen_graph.get("screen-001").type == "purchase"
    empty_context, empty_state = asyncio.run(
        Explorer(frame_source=StaticFrameSource([_frame()])).explore(
            BuildContext.create(GoalSpec(app_name="Empty", goal="open", budgets=BuilderBudgets(max_exploration_depth=1)), SafetyPolicy())
        )
    )
    assert empty_state.status == "ok"
    assert empty_context.screen_graph.get("screen-001")
    async def broken_execute(_action):
        raise RuntimeError("broken action")
    failed_context, failed_state = asyncio.run(
        Explorer(
            frame_source=StaticFrameSource([_frame()]),
            candidate_finder=candidates,
            action_executor=broken_execute,
        ).explore(BuildContext.create(GoalSpec(app_name="Fail", goal="open", budgets=BuilderBudgets(max_exploration_depth=1)), SafetyPolicy()))
    )
    assert failed_state.status == "failed"
    assert failed_context.screen_graph.get("screen-001")


def test_profile_roi_scenario_replay_live_and_healing_edges(tmp_path):
    graph = ScreenGraph()
    goal = GoalSpec(app_name="Candy", goal="play", runtime_strategy="match3")
    profile = generate_profile(goal, graph, {"safe_elements": [{"roi": "board", "normalized_box": [0.1, 0.2, 0.9, 0.8]}]})
    assert profile["screen_zones"]["board"] == [0.1, 0.2, 0.9, 0.8]
    zones = generate_roi_zones(
        strategy="generic_app",
        labels=[{"name": "manual", "normalizedBox": [0.1, 0.1, 0.2, 0.2]}],
        analysis={"safe_elements": [{"roi": "popup", "normalized_box": [0.3, 0.3, 0.4, 0.4]}]},
    )
    assert zones["manual"] == [0.1, 0.1, 0.2, 0.2]
    assert zones["popup"] == [0.3, 0.3, 0.4, 0.4]
    with pytest.raises(RuntimeError, match="scenario step blocked"):
        generate_scenario(goal, profile, graph, SafetyPolicy(forbidden_actions=["play_button"]))
    frame = tmp_path / "frame.png"
    frame.write_bytes(_png())
    failed = asyncio.run(run_replay_tests({"profile": {}, "scenario": {}}, frame_paths=[frame], templates_root=tmp_path))
    assert failed["status"] == "failed"
    fast_failed = asyncio.run(
        run_replay_tests(
            {"profile": {"screen_zones": {"x": [0, 0, 1, 1]}, "runtime": {}}, "scenario": {"steps": [{"type": "enter_fast_gameplay"}]}},
            frame_paths=[frame],
            templates_root=tmp_path,
        )
    )
    assert "fast gameplay must be local_only" in fast_failed["failures"]
    assert run_live_validation({"profile": {}, "scenario": {}})["status"] == "failed"
    assert run_live_validation({"profile": {"package": "missing"}, "scenario": {}}, runner=lambda a, t: subprocess.CompletedProcess(a, 1, stdout=b"", stderr=b""))["status"] == "failed"
    live_fast = run_live_validation(
        {"profile": {"package": "pkg", "runtime": {}}, "scenario": {"steps": [{"type": "enter_fast_gameplay"}]}},
        runner=lambda a, t: subprocess.CompletedProcess(a, 0, stdout=b"package:/x\n" if "pm path" in " ".join(a) else b"", stderr=b""),
        policy=SafetyPolicy(),
    )
    assert live_fast["status"] == "failed"
    healing = SelfHealingEngine(policy=SafetyPolicy()).propose_patch(
        {},
        {"safe_elements": ["bad", {"name": "new_roi", "roi": "popup", "normalized_box": [0.1, 0.1, 0.2, 0.2]}]},
    )
    assert healing["patches"][0]["type"] == "add_roi"


def test_screen_analyst_api_key_path_and_parse_edges(monkeypatch):
    payload = {
        "screen_type": "menu",
        "summary": "ok",
        "safe_elements": [42, {"name": "ok_button"}],
        "risky_elements": [42, {"name": "shop"}],
        "next_best_goal": "tap_ok",
    }

    class CV:
        def __init__(self, api_key="", models=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def _call_vision(self, prompt, screenshot):
            return "{}"

        def _extract_json_from_text(self, result):
            return payload

    monkeypatch.setattr(builder_module, "ScreenAnalyst", ScreenAnalyst)
    import core.autobuilder.screen_analyst as analyst_module

    monkeypatch.setattr(analyst_module, "CVEngine", CV)
    result = asyncio.run(
        ScreenAnalyst(api_key="key").analyze(
            screenshot=b"png",
            visible_texts=["OK"],
            goal=GoalSpec(app_name="Game", goal="open"),
            policy=SafetyPolicy(),
            screen_graph=ScreenGraph(),
        )
    )
    assert result.safe_elements == [{"name": "ok_button"}]
    assert result.risky_elements == [{"name": "shop"}]
    with pytest.raises(RuntimeError, match="requires api_key"):
        asyncio.run(ScreenAnalyst()._call("prompt", b"png"))

    class BadCV(CV):
        def _extract_json_from_text(self, result):
            return []

    monkeypatch.setattr(analyst_module, "CVEngine", BadCV)
    with pytest.raises(RuntimeError, match="invalid JSON"):
        asyncio.run(ScreenAnalyst(api_key="key")._call("prompt", b"png"))
    with pytest.raises(SchemaValidationError):
        _parse_analysis({"screen_type": "menu", "summary": "x", "safe_elements": "bad", "risky_elements": [], "next_best_goal": ""})


def test_builder_launch_live_blank_serial_and_helpers(tmp_path, monkeypatch):
    path = tmp_path / "screen.png"
    path.write_bytes(_png())

    def runner(args, timeout):
        joined = " ".join(args)
        if "pm path com.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"package:/base.apk\n", stderr=b"")
        if "dumpsys package com.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"versionName=1\nversionCode=2 minSdk=23\n", stderr=b"")
        if "dumpsys window" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"mFocusedApp=AppWindowToken{com.game/.Main}\n", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    builder = builder_module.AutopilotBuilder()
    result = builder.build(
        "Create app: Custom Game. Open menu.",
        builder_module.BuildOptions(
            package="com.game",
            output_root=tmp_path / "out",
            frame_paths=[path],
            live_validation=True,
            runner=runner,
        ),
    )
    assert result["live_report"]["status"] == "passed"
    skipped = builder.build(
        "Create app: Missing Game. Open menu.",
        builder_module.BuildOptions(package="missing", output_root=tmp_path / "missing", frame_paths=[path], runner=lambda a, t: subprocess.CompletedProcess(a, 1, stdout=b"", stderr=b"")),
    )
    assert skipped["bundle"]["autopilot"]["app_name"] == "Missing Game"
    assert builder._get_frame(builder_module.BuildOptions()).source_name == "blank"
    assert builder._analyze_screen(Frame(1, 1, 1, None, None, "empty", 0), GoalSpec(app_name="x", goal="x"), SafetyPolicy(), ScreenGraph(), BuildContext.create(GoalSpec(app_name="x", goal="x"), SafetyPolicy()), builder_module.BuildOptions())["screen_type"] == "unknown"
    assert builder_module._first_screen_id(ScreenGraph()) == ""

    class FakeAdbSource:
        def __init__(self, **kwargs):
            pass

        async def latest_frame(self):
            return _frame()

    monkeypatch.setattr(builder_module, "AdbScreencapSource", FakeAdbSource)
    assert builder._get_frame(builder_module.BuildOptions(serial="device")).source_name == "test"
    assert asyncio.run(builder_module._SingleFrameSource(_frame()).latest_frame()).width == 32


def test_task_parser_template_miner_and_review_edges(tmp_path):
    assert _extract_goal("", "App") == "Build autopilot for App"
    assert parse_goal_prompt("").app_name == "Custom App"
    assert parse_goal_prompt("brawl onboarding").app_name == "Brawl Stars"
    assert _selector_matches("", "text") is False
    assert _selector_matches("bs", "play bs now") is True
    assert _selector_matches("bs", "absolute") is False
    assert _valid_bbox("bad", (10, 10)) is False
    assert _valid_bbox([0, 0, 2, 2], (10, 10)) is False
    assert mine_templates(frame=Frame(1, 1, 1, None, None, "empty", 0), elements=[], output_root=tmp_path, namespace="x") == {"templates": [], "verified": []}
    image = Image.new("RGB", (20, 20), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    frame = Frame(1, 20, 20, None, buf.getvalue(), "test", 0)
    result = mine_templates(frame=frame, elements=[{"name": "bad", "bbox": [0, 0, 2, 2], "confidence": 0.9}], output_root=tmp_path, namespace="x")
    assert result["templates"] == []
    registry = tmp_path / "registry.json"
    registry.write_text('[{"id":"old","paths":["old.png"]}]', encoding="utf-8")
    mine_templates(frame=frame, elements=[], output_root=tmp_path, namespace="x")
    assert "old" in registry.read_text(encoding="utf-8")
    queue = PatchReviewQueue(tmp_path)
    review = queue.submit(AutopilotPatch(type="add_screen"), ttl_ms=-1)
    assert queue.decide(review["id"], approve=True)["status"] == "expired"
    with pytest.raises(RuntimeError, match="not pending"):
        queue.decide(review["id"], approve=True)
    from core.autobuilder.versioning import AutopilotVersionStore
    with pytest.raises(RuntimeError, match="unknown version"):
        AutopilotVersionStore(tmp_path).rollback("9.9.9")
