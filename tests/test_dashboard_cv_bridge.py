import asyncio
import subprocess

import pytest

from core.cv_engine import UIActionPlan
from core.metrics import metrics_snapshot, reset_metrics
from dashboard import cv_bridge
from dashboard.cv_bridge import DashboardAdbAction


PNG_1X1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00"
)


class RecordingRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, timeout):
        self.calls.append((cmd, timeout))
        if cmd[-3:] == ["exec-out", "screencap", "-p"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=PNG_1X1, stderr=b"")
        return subprocess.CompletedProcess(cmd, 0, stdout=b"ok", stderr=b"")


def test_dashboard_adb_action_wraps_screenshot_and_input_commands():
    runner = RecordingRunner()
    action = DashboardAdbAction("emu", adb_path="adb-test", runner=runner)

    screenshot = asyncio.run(action.screenshot())
    asyncio.run(action.tap(10, 20, pause=0))
    asyncio.run(action.type_text("a b&$", pause=0))
    asyncio.run(action.press_back())
    asyncio.run(action.swipe_up())

    commands = [call[0] for call in runner.calls]
    assert screenshot == PNG_1X1
    assert action._real_screen_w == 1
    assert commands[0] == ["adb-test", "-s", "emu", "exec-out", "screencap", "-p"]
    assert ["adb-test", "-s", "emu", "shell", "input", "tap", "10", "20"] in commands
    assert ["adb-test", "-s", "emu", "shell", "input", "text", r"a%sb\&\$"] in commands
    assert ["adb-test", "-s", "emu", "shell", "input", "keyevent", "4"] in commands
    assert any(command[4:7] == ["input", "swipe", "0"] for command in commands)


def test_dashboard_adb_action_covers_extra_keys_pause_and_error_paths(monkeypatch):
    sleeps = []

    async def fake_sleep(seconds):
        sleeps.append(seconds)

    monkeypatch.setattr(cv_bridge.asyncio, "sleep", fake_sleep)

    runner = RecordingRunner()
    action = DashboardAdbAction("", adb_path="adb-test", runner=runner)
    assert action._adb_cmd("shell", "echo") == ["adb-test", "shell", "echo"]

    assert asyncio.run(action._run_adb("shell", "echo")) == "ok"
    asyncio.run(action.tap(1, 2))
    asyncio.run(action.type_text("text"))
    asyncio.run(action.swipe_down())
    asyncio.run(action.clear_field())
    asyncio.run(action.press_home())
    asyncio.run(action.press_enter())
    asyncio.run(action.press_tab())

    commands = [call[0] for call in runner.calls]
    assert sleeps == [0.3, 0.3]
    assert ["adb-test", "shell", "input", "keyevent", "3"] in commands
    assert ["adb-test", "shell", "input", "keyevent", "66"] in commands
    assert ["adb-test", "shell", "input", "keyevent", "61"] in commands


def test_dashboard_adb_screenshot_errors_and_default_runner(monkeypatch):
    class FailingRunner:
        def __call__(self, cmd, timeout):
            return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"bad screenshot")

    class TextRunner:
        def __call__(self, cmd, timeout):
            return subprocess.CompletedProcess(cmd, 0, stdout=b"not-png", stderr=b"")

    with pytest.raises(RuntimeError, match="bad screenshot"):
        asyncio.run(DashboardAdbAction("emu", runner=FailingRunner()).screenshot())
    with pytest.raises(RuntimeError, match="did not return PNG"):
        asyncio.run(DashboardAdbAction("emu", runner=TextRunner()).screenshot())

    calls = []

    def fake_run(*args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args[0], 0, stdout=b"ok", stderr=b"")

    monkeypatch.setattr(cv_bridge.subprocess, "run", fake_run)

    assert cv_bridge._default_runner(["adb", "devices"], 3).stdout == b"ok"
    assert calls[0][1]["timeout"] == 3


def test_payload_helpers_parse_values_models_and_recent_actions(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "env-key")
    payload = {
        "values": {"code": 123},
        "recentActions": ["tap:start"],
        "models": "model-a, model-b",
    }

    assert cv_bridge.payload_values(payload) == {"code": "123"}
    assert cv_bridge.payload_recent_actions(payload) == ["tap:start"]
    assert cv_bridge.payload_models(payload) == ["model-a", "model-b"]
    assert cv_bridge.payload_models({"models": ["model-c", "", "model-d"]}) == ["model-c", "model-d"]
    assert cv_bridge.payload_models({"models": []}) is None
    assert cv_bridge.payload_models({"models": 42}) is None
    assert cv_bridge.payload_api_key({"apiKey": "payload-key"}) == "payload-key"
    assert cv_bridge.payload_api_key({"openrouterKey": "   "}) == "env-key"
    assert cv_bridge.payload_api_key({}) == "env-key"
    assert cv_bridge.payload_values({"values": 42}) == {}
    assert cv_bridge.payload_recent_actions({"recentActions": "bad"}) == []


def test_require_vision_api_key_rejects_blank_before_adb(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    assert cv_bridge.require_vision_api_key(" token ") == "token"
    assert cv_bridge.payload_api_key({"openrouterKey": "   ", "apiKey": ""}) == ""

    runner = RecordingRunner()
    with pytest.raises(RuntimeError, match="Vision API key is required"):
        asyncio.run(cv_bridge.plan_cv_action(
            serial="emu",
            goal="continue",
            api_key="",
            adb_path="adb-test",
            runner=runner,
        ))
    assert runner.calls == []


def test_plan_cv_action_uses_screenshot_and_returns_plan(monkeypatch):
    reset_metrics()
    runner = RecordingRunner()

    class FakeCVEngine:
        def __init__(self, api_key=None, models=None):
            self.api_key = api_key
            self.models = models

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        @staticmethod
        def _get_png_dimensions(data):
            return 1, 1

        async def plan_next_ui_action(self, screenshot, goal, available_values, recent_actions):
            assert screenshot == PNG_1X1
            assert goal == "continue"
            assert available_values == {"name": "Player"}
            assert recent_actions == ["tap:start"]
            return UIActionPlan(action="tap", x=1, y=1, reason="next")

    monkeypatch.setattr(cv_bridge, "CVEngine", FakeCVEngine)

    result = asyncio.run(cv_bridge.plan_cv_action(
        serial="emu",
        goal="continue",
        values={"name": "Player"},
        recent_actions=["tap:start"],
        api_key="key",
        models=["model"],
        adb_path="adb-test",
        runner=runner,
    ))

    assert result["serial"] == "emu"
    assert result["plan"]["action"] == "tap"
    assert result["screen"]["png_bytes"] == len(PNG_1X1)
    trace = metrics_snapshot()["latest_trace"]
    assert trace["providers_called"] == ["llm_plan"]
    assert trace["selected_candidate"]["name"] == "tap"
    assert trace["selected_candidate"]["bbox"] == (0, 0, 1, 1)
    assert trace["action"]["outcome"] == "planned"


def test_run_cv_goal_stops_before_risky_purchase_actions(monkeypatch):
    runner = RecordingRunner()

    class FakeRiskyCV:
        def __init__(self, api_key=None, models=None):
            self.api_key = api_key
            self.models = models

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        @staticmethod
        def _get_png_dimensions(data):
            return 1, 1

        async def plan_next_ui_action(self, screenshot, goal, available_values, recent_actions):
            return UIActionPlan(action="tap", target="Buy now", x=10, y=20, reason="purchase button visible")

    monkeypatch.setattr(cv_bridge, "CVEngine", FakeRiskyCV)

    result = asyncio.run(cv_bridge.run_cv_goal(
        serial="emu",
        goal="reach purchase preview",
        max_steps=5,
        api_key="key",
        adb_path="adb-test",
        runner=runner,
    ))

    commands = [call[0] for call in runner.calls]
    assert result["ok"] is True
    assert result["steps"][0]["outcome"] == "done"
    assert not any(command[4:7] == ["input", "tap", "10"] for command in commands)
