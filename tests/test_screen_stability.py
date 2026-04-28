import asyncio
from io import BytesIO

from PIL import Image, ImageDraw

from core.frame_source import Frame
from core.perception.screen_stability import ScreenStabilityDetector, wait_until_stable


def _png(color: str = "white", *, moving_box: tuple[int, int, int, int] | None = None) -> bytes:
    image = Image.new("RGB", (120, 120), color)
    if moving_box:
        draw = ImageDraw.Draw(image)
        draw.rectangle(moving_box, fill="black")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frame(png: bytes) -> Frame:
    return Frame(
        timestamp_ms=1,
        width=120,
        height=120,
        rgb_or_bgr_array=None,
        png_bytes=png,
        source_name="test",
        latency_ms=0.1,
    )


class FakeFrameSource:
    def __init__(self, frames):
        self.frames = list(frames)
        self.index = 0

    async def latest_frame(self):
        frame = self.frames[min(self.index, len(self.frames) - 1)]
        self.index += 1
        return frame


def test_screen_stability_becomes_stable_after_repeated_frames():
    detector = ScreenStabilityDetector(window_size=3, diff_threshold=1.0)
    frame = _frame(_png("white"))

    first = detector.observe(frame)
    second = detector.observe(frame)
    third = detector.observe(frame)

    assert first.stable is False
    assert first.reason == "warming_up"
    assert second.stable is False
    assert third.stable is True
    assert third.reason == "stable"
    assert third.mean_diff == 0.0


def test_screen_stability_detects_changing_frames():
    detector = ScreenStabilityDetector(window_size=3, diff_threshold=1.0)

    detector.observe(_frame(_png("white", moving_box=(0, 0, 20, 20))))
    detector.observe(_frame(_png("white", moving_box=(30, 30, 50, 50))))
    result = detector.observe(_frame(_png("white", moving_box=(60, 60, 80, 80))))

    assert result.stable is False
    assert result.reason == "changing"
    assert result.mean_diff > 1.0


def test_screen_stability_can_focus_on_roi():
    detector = ScreenStabilityDetector(window_size=2, diff_threshold=1.0)
    first = _frame(_png("white", moving_box=(0, 0, 20, 20)))
    second = _frame(_png("white", moving_box=(90, 90, 110, 110)))

    detector.observe(first, roi=(40, 40, 80, 80))
    result = detector.observe(second, roi=(40, 40, 80, 80))

    assert result.stable is True
    assert result.mean_diff == 0.0


def test_screen_stability_reset_and_missing_png_error():
    detector = ScreenStabilityDetector(window_size=2)
    detector.observe(_frame(_png("white")))
    detector.reset()

    result = detector.observe(_frame(_png("white")))

    assert result.reason == "warming_up"
    try:
        detector.observe(b"")
    except RuntimeError as exc:
        assert "PNG" in str(exc)
    else:
        raise AssertionError("missing png should fail")


def test_wait_until_stable_returns_when_detector_is_stable():
    stable_frame = _frame(_png("white"))
    source = FakeFrameSource([stable_frame, stable_frame, stable_frame])

    result = asyncio.run(
        wait_until_stable(
            source,
            detector=ScreenStabilityDetector(window_size=3, diff_threshold=1.0),
            timeout_ms=1000,
            poll_interval_ms=1,
        )
    )

    assert result.stable is True
    assert result.reason == "stable"
    assert source.index == 3


def test_wait_until_stable_times_out_when_frames_keep_changing():
    class ChangingSource:
        def __init__(self):
            self.index = 0

        async def latest_frame(self):
            self.index += 1
            offset = 10 if self.index % 2 else 60
            return _frame(_png("white", moving_box=(offset, offset, offset + 10, offset + 10)))

    source = ChangingSource()

    result = asyncio.run(
        wait_until_stable(
            source,
            detector=ScreenStabilityDetector(window_size=2, diff_threshold=0.0),
            timeout_ms=1,
            poll_interval_ms=0,
        )
    )

    assert result.stable is False
    assert result.reason == "timeout"
