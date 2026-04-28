"""End-to-end Autopilot Builder orchestrator."""
from __future__ import annotations

import asyncio
import hashlib
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from core.autobuilder.app_manager import AppManager
from core.autobuilder.bundle import load_autopilot_bundle, save_autopilot_bundle
from core.autobuilder.context import BuildContext
from core.autobuilder.eval_suite import evaluate_autopilot
from core.autobuilder.explorer import Explorer
from core.autobuilder.goal_spec import GoalSpec
from core.autobuilder.live_validation import run_live_validation
from core.autobuilder.live_exploration import default_live_exploration_actions, run_live_exploration
from core.autobuilder.profile_generator import generate_profile
from core.autobuilder.replay_test_runner import run_replay_tests
from core.autobuilder.roi_generator import generate_roi_zones
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.scenario_generator import generate_scenario
from core.autobuilder.screen_analyst import ScreenAnalyst
from core.autobuilder.screen_graph import ScreenGraph
from core.autobuilder.self_healing import SelfHealingEngine
from core.autobuilder.task_parser import parse_goal_prompt
from core.autobuilder.template_miner import mine_templates
from core.autobuilder.versioning import AutopilotVersionStore
from core.frame_source import Frame, FrameSource, ReplayFrameSource, close_frame_source, create_frame_source, timestamp_ms


class BuildOptions:
    def __init__(
        self,
        *,
        mode: str = "create",
        serial: str = "",
        package: str = "",
        api_key: str = "",
        models: list[str] | None = None,
        adb_path: str = "adb",
        output_root: str | Path = "autopilots",
        templates_root: str | Path = "assets/templates",
        frame_paths: list[str | Path] | None = None,
        live_exploration_actions: list[dict[str, Any]] | None = None,
        live_validation: bool = False,
        launch_app: bool = True,
        llm=None,
        runner=None,
    ):
        self.mode = mode
        self.serial = serial
        self.package = package
        self.api_key = api_key
        self.models = models
        self.adb_path = adb_path
        self.output_root = Path(output_root)
        self.templates_root = Path(templates_root)
        self.frame_paths = list(frame_paths or [])
        self.live_exploration_actions = live_exploration_actions
        self.live_validation = live_validation
        self.launch_app = launch_app
        self.llm = llm
        self.runner = runner


class AutopilotBuilder:
    def build(self, prompt: str, options: BuildOptions | None = None) -> dict[str, Any]:
        options = options or BuildOptions()
        goal = parse_goal_prompt(prompt, mode=options.mode, package=options.package)
        policy = SafetyPolicy.from_goal(goal)
        context = BuildContext.create(goal, policy)
        stages: list[dict[str, Any]] = []
        live_exploration_report: dict[str, Any] = {"status": "skipped", "actions": [], "failures": [], "metrics": {}}
        frame = self._get_frame(options)
        app_info = {}
        if options.package and options.launch_app:
            manager = AppManager(
                serial=options.serial,
                adb_path=options.adb_path,
                policy=policy,
                runner=options.runner,
                test_device=True,
            )
            if manager.check_installed(options.package):
                app_info = manager.launch_app(options.package).to_dict()
                stages.append({"step": "launching_app", "status": "ok", "app": app_info})
                frame = self._get_frame(options)
            else:
                stages.append({"step": "launching_app", "status": "skipped", "reason": "app_not_installed"})
        context = context.with_updates(app_info=app_info)
        graph = ScreenGraph()
        replay_dir = options.output_root / goal.autopilot_id / "replays" / "frames"
        replay_dir.mkdir(parents=True, exist_ok=True)
        replay_frame_paths: list[Path] = []
        if options.serial and options.live_exploration_actions is not None:
            live_exploration = run_live_exploration(
                serial=options.serial,
                adb_path=options.adb_path,
                actions=options.live_exploration_actions or default_live_exploration_actions(),
                output_dir=replay_dir,
                policy=policy,
                runner=options.runner,
            )
            live_exploration_report = live_exploration.to_report()
            stages.append({"step": "live_exploration", "status": live_exploration.state.status, "metrics": live_exploration_report["metrics"]})
            graph = live_exploration.graph
            exploration = live_exploration.state
            replay_frame_paths = list(live_exploration.frame_paths)
            if replay_frame_paths:
                source = ReplayFrameSource(replay_frame_paths)
                try:
                    frame = asyncio.run(source.latest_frame())
                finally:
                    close_frame_source(source)
        else:
            context, exploration = asyncio.run(Explorer(frame_source=_SingleFrameSource(frame)).explore(context.with_updates(screen_graph=graph)))
            graph = context.screen_graph or graph
        initial_screen_id = _first_screen_id(graph) or "screen_001"
        analysis = self._analyze_screen(frame, goal, policy, graph, context, options)
        graph.add_screen(
            screen_id=initial_screen_id,
            screen_hash=hash_frame(frame.png_bytes or b""),
            screen_type=analysis.get("screen_type", "unknown"),
            texts=[],
            elements=[item.get("name", "") for item in analysis.get("safe_elements", [])],
            safe_actions=[item.get("recommended_action", "") for item in analysis.get("safe_elements", [])],
            risky_actions=[item.get("name", "") for item in analysis.get("risky_elements", [])],
        )
        context = context.with_updates(screen_graph=graph)
        profile = generate_profile(goal, graph, analysis)
        profile["screen_zones"] = generate_roi_zones(
            strategy=goal.runtime_strategy,
            screen_width=frame.width,
            screen_height=frame.height,
            analysis=analysis,
        )
        scenario = generate_scenario(goal, profile, graph, policy)
        frame_path = replay_dir / "frame_000.png"
        if not replay_frame_paths and frame.png_bytes:
            frame_path.write_bytes(frame.png_bytes)
            replay_frame_paths = [frame_path]
        templates = mine_templates(
            frame=frame,
            elements=analysis.get("safe_elements", []),
            output_root=options.output_root / goal.autopilot_id / "templates",
            namespace=goal.autopilot_id,
        )
        build_report = {
            "status": "ok",
            "goal_spec": goal.to_dict(),
            "analysis": analysis,
            "template_mining": templates,
            "stages": stages,
            "exploration": exploration.to_dict(),
            "live_exploration": live_exploration_report,
            "metrics": context.metrics,
            "trace": context.trace,
        }
        bundle_result = save_autopilot_bundle(
            root=options.output_root,
            goal=goal,
            safety_policy=policy,
            profile=profile,
            scenario=scenario,
            screen_graph=graph,
            reports=build_report,
        )
        loaded = load_autopilot_bundle(bundle_result["bundle_dir"])
        replay_report = asyncio.run(
            run_replay_tests(
                loaded,
                frame_paths=replay_frame_paths or [frame_path],
                templates_root=options.output_root / goal.autopilot_id / "templates",
            )
        )
        live_report = {"status": "skipped", "failures": [], "actions": [], "metrics": {}}
        if options.live_validation:
            live_report = run_live_validation(
                loaded,
                serial=options.serial,
                adb_path=options.adb_path,
                runner=options.runner,
                policy=policy,
            )
        repair = SelfHealingEngine(policy=policy, budget_counter=context.budget_counter).propose_patch(
            {"expected": "initial_validation", "actual": replay_report["status"]},
            analysis,
        )
        eval_report = evaluate_autopilot([
            {"status": replay_report["status"], "llm_calls": 1 if analysis else 0, "forbidden_actions_count": 0},
            {"status": live_report["status"], "llm_calls": 0, "forbidden_actions_count": 0},
        ])
        version = AutopilotVersionStore(bundle_result["bundle_dir"]).add_version(
            "0.1.0",
            change="initial build",
            test_result={"replay": replay_report, "live": live_report},
        )
        status = "ok"
        if replay_report["status"] != "passed" or live_exploration_report.get("status") == "failed":
            status = "warning"
        return {
            "status": status,
            "goal_spec": goal.to_dict(),
            "bundle": bundle_result,
            "profile": profile,
            "scenario": scenario,
            "screen_graph": graph.to_dict(),
            "analysis": analysis,
            "template_mining": templates,
            "exploration": exploration.to_dict(),
            "live_exploration": live_exploration_report,
            "replay_report": replay_report,
            "live_report": live_report,
            "repair": repair,
            "eval_report": eval_report,
            "version": version,
        }

    def _get_frame(self, options: BuildOptions) -> Frame:
        if options.frame_paths:
            source = ReplayFrameSource(options.frame_paths)
            try:
                return asyncio.run(source.latest_frame())
            finally:
                close_frame_source(source)
        if options.serial:
            source = create_frame_source(serial=options.serial)
            try:
                return asyncio.run(source.latest_frame())
            finally:
                close_frame_source(source)
        return _blank_frame()

    def _analyze_screen(
        self,
        frame: Frame,
        goal: GoalSpec,
        policy: SafetyPolicy,
        graph: ScreenGraph,
        context: BuildContext,
        options: BuildOptions,
    ) -> dict[str, Any]:
        if not frame.png_bytes:
            return _fallback_analysis(goal)
        if options.api_key or options.llm:
            analyst = ScreenAnalyst(api_key=options.api_key, models=options.models, llm=options.llm, max_retries=1)
            return asyncio.run(
                analyst.analyze(
                    screenshot=frame.png_bytes,
                    visible_texts=[],
                    goal=goal,
                    policy=policy,
                    screen_graph=graph,
                    budget_counter=context.budget_counter,
                )
            ).to_dict()
        return _fallback_analysis(goal)


def _blank_frame() -> Frame:
    image = Image.new("RGB", (320, 640), "black")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    png = buffer.getvalue()
    return Frame(timestamp_ms=timestamp_ms(), width=320, height=640, rgb_or_bgr_array=None, png_bytes=png, source_name="blank", latency_ms=0)


def hash_frame(png_bytes: bytes) -> str:
    return hashlib.sha256(png_bytes or b"").hexdigest()[:16]


def _first_screen_id(graph: ScreenGraph) -> str:
    for screen in graph.screens.values():
        return screen.screen_id
    return ""


class _SingleFrameSource(FrameSource):
    def __init__(self, frame: Frame):
        self.frame = frame

    async def latest_frame(self) -> Frame:
        return self.frame


def _fallback_analysis(goal: GoalSpec) -> dict[str, Any]:
    return {
        "screen_type": "unknown",
        "summary": f"Fallback analysis for {goal.app_name}; no LLM/device screen was available.",
        "safe_elements": [],
        "risky_elements": [],
        "next_best_goal": goal.goal,
    }
