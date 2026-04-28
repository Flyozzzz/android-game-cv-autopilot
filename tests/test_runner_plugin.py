from io import BytesIO

from PIL import Image, ImageDraw

from core.gameplay.runner_plugin import RunnerPlugin, RunnerState
from core.gameplay.base_plugin import GameplayAction


def _png_with_obstacles(*lanes: int) -> bytes:
    image = Image.new("RGB", (300, 600), "white")
    draw = ImageDraw.Draw(image)
    lane_width = 80
    x_pad = 30
    for lane in lanes:
        x1 = x_pad + lane * lane_width + 12
        x2 = x1 + 56
        draw.rectangle((x1, 360, x2, 500), fill="black")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_runner_plugin_starts_running_when_lane_is_clear():
    plugin = RunnerPlugin()

    decision = plugin.decide(_png_with_obstacles())

    assert decision.action.gesture == "none"
    assert decision.state == RunnerState.RUNNING
    assert decision.danger is False


def test_runner_plugin_emits_lane_change_with_cooldown_key():
    plugin = RunnerPlugin()

    decision = plugin.decide(_png_with_obstacles(0, 1))

    assert decision.action.gesture == "right"
    assert decision.action.cooldown_key == "lane_change"
    assert decision.state == RunnerState.LANE_SWITCHING
    assert decision.danger is True
    assert decision.action.confidence > 0


def test_runner_plugin_emits_jump_state_when_all_lanes_are_blocked():
    plugin = RunnerPlugin()

    decision = plugin.decide(_png_with_obstacles(0, 1, 2))

    assert decision.action.gesture == "up"
    assert decision.action.cooldown_key == "jump"
    assert decision.state == RunnerState.JUMPING


def test_runner_plugin_frame_skip_policy_keeps_last_state():
    plugin = RunnerPlugin(frame_skip=2)

    first = plugin.decide(_png_with_obstacles(0, 1))
    second = plugin.decide(_png_with_obstacles(0, 1, 2))
    third = plugin.decide(_png_with_obstacles(0, 1, 2))

    assert first.frame_index == 1
    assert first.action.gesture == "right"
    assert second.frame_index == 2
    assert second.action.gesture == "none"
    assert second.action.reason == "frame skipped"
    assert second.state == RunnerState.LANE_SWITCHING
    assert third.frame_index == 3
    assert third.action.gesture == "up"


def test_runner_plugin_gesture_points_are_resolution_relative():
    assert RunnerPlugin.gesture_points(1000, 2000, "left") == (550, 1480, 250, 1480)
    assert RunnerPlugin.gesture_points(1000, 2000, "up") == (500, 1520, 500, 840)


def test_runner_plugin_handles_missing_frame_and_duck_state():
    plugin = RunnerPlugin()

    decision = plugin.decide(b"")

    assert decision.state == RunnerState.UNKNOWN
    assert decision.action.gesture == "none"
    assert RunnerPlugin._next_state(GameplayAction("down", "duck")) == RunnerState.DUCKING
    assert GameplayAction("left", "move").is_noop is False
