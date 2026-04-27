from io import BytesIO

from PIL import Image, ImageDraw

from core.fast_runner import FastRunnerDetector


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


def test_fast_runner_detector_does_nothing_when_clear():
    decision = FastRunnerDetector().decide(_png_with_obstacles())

    assert decision.gesture == "none"


def test_fast_runner_detector_moves_to_clearer_right_lane():
    decision = FastRunnerDetector().decide(_png_with_obstacles(0, 1))

    assert decision.gesture == "right"


def test_fast_runner_detector_jumps_when_center_blocked_and_sides_unclear():
    decision = FastRunnerDetector().decide(_png_with_obstacles(0, 1, 2))

    assert decision.gesture == "up"
