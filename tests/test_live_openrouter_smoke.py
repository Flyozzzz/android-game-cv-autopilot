import asyncio
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from core.autobuilder.builder import AutopilotBuilder, BuildOptions
from core.cv_engine import CVEngine


pytestmark = [pytest.mark.integration, pytest.mark.live_adb, pytest.mark.live_openrouter]


def _adb_path() -> str:
    return os.getenv("ADB_PATH") or shutil.which("adb") or "adb"


def _connected_devices() -> list[str]:
    proc = subprocess.run(
        [_adb_path(), "devices", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return []
    serials = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _target_serial() -> str:
    devices = _connected_devices()
    if not devices:
        pytest.skip("No live ADB device connected")
    requested = (os.getenv("LOCAL_DEVICE") or "").strip()
    if requested and requested.lower() not in {"auto", "first"}:
        if requested not in devices:
            pytest.skip(f"LOCAL_DEVICE={requested} not connected; connected={devices}")
        return requested
    return devices[0]


def _vision_key() -> str:
    key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not key:
        pytest.skip("OPENROUTER_API_KEY is required for live OpenRouter smoke")
    return key


def _vision_models() -> list[str]:
    models = [item.strip() for item in os.getenv("CV_MODELS", "xiaomi/mimo-v2.5").split(",") if item.strip()]
    return models or ["xiaomi/mimo-v2.5"]


def _capture_png(serial: str) -> bytes:
    proc = subprocess.run(
        [_adb_path(), "-s", serial, "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="ignore")
    assert proc.stdout.startswith(b"\x89PNG\r\n\x1a\n")
    return proc.stdout


def _package_installed(serial: str, package: str) -> bool:
    proc = subprocess.run(
        [_adb_path(), "-s", serial, "shell", "pm", "path", package],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=10,
    )
    return proc.returncode == 0 and bool(proc.stdout.strip())


def test_live_openrouter_cv_plan_and_autopilot_builder_use_real_device_frame(tmp_path):
    """Exercise real Vision planning and multi-step Builder exploration."""

    api_key = _vision_key()
    models = _vision_models()
    serial = _target_serial()
    screenshot = _capture_png(serial)
    frame_path = tmp_path / "live_frame.png"
    frame_path.write_bytes(screenshot)
    with Image.open(frame_path) as image:
        width, height = image.size

    async def plan_once():
        async with CVEngine(api_key=api_key, models=models) as cv:
            return await cv.plan_next_ui_action(
                screenshot,
                goal=(
                    "Live smoke test only: identify the current screen and choose wait "
                    "unless there is a clearly safe non-purchase UI action."
                ),
                available_values={},
                recent_actions=[],
            )

    plan = asyncio.run(plan_once())
    assert plan.action in {"tap", "type", "press", "swipe", "wait", "done", "fail"}
    if plan.action in {"tap", "type"}:
        assert 0 <= plan.x <= width
        assert 0 <= plan.y <= height

    package = "com.android.settings"
    if not _package_installed(serial, package):
        pytest.skip(f"{package} is not installed on {serial}")

    exploration_actions = [
        {"type": "swipe", "direction": "up", "name": "safe_scroll_up"},
        {"type": "swipe", "direction": "down", "name": "safe_scroll_down"},
        {"type": "swipe", "direction": "left", "name": "safe_swipe_left"},
        {"type": "swipe", "direction": "right", "name": "safe_swipe_right"},
    ]

    result = AutopilotBuilder().build(
        "Create autopilot for Android Settings. Explore safely. No purchases, no login, no account changes.",
        BuildOptions(
            api_key=api_key,
            models=models,
            serial=serial,
            package=package,
            output_root=tmp_path / "autopilots",
            live_exploration_actions=exploration_actions,
            launch_app=True,
            live_validation=False,
        ),
    )

    assert result["status"] in {"ok", "warning"}
    assert result["goal_spec"]["app_name"] == "Android Settings"
    assert result["analysis"]["screen_type"]
    assert result["live_exploration"]["status"] == "ok"
    assert result["live_exploration"]["metrics"]["actions"] >= 4
    assert result["live_exploration"]["metrics"]["frames"] >= 5
    assert result["live_exploration"]["metrics"]["transitions"] >= 4
    assert len(result["exploration"]["steps"]) >= 4
    bundle_dir = Path(result["bundle"]["bundle_dir"])
    assert (bundle_dir / "autopilot.json").exists()
    assert (bundle_dir / "profile.json").exists()
    assert (bundle_dir / "scenario.json").exists()
    assert (bundle_dir / "screen_graph.json").exists()
    assert json.loads((bundle_dir / "profile.json").read_text(encoding="utf-8"))["screen_zones"]
    assert len(json.loads((bundle_dir / "screen_graph.json").read_text(encoding="utf-8"))["transitions"]) >= 4
