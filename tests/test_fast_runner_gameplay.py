import asyncio
from io import BytesIO

from PIL import Image

import config
from core.metrics import metrics_snapshot, reset_metrics
from scenarios.fast_runner_gameplay import FastRunnerGameplayScenario


class FakeAction:
    _real_screen_w = 300
    _real_screen_h = 600

    def __init__(self):
        self.screenshots = 0
        self.swipes = []

    async def screenshot(self):
        self.screenshots += 1
        image = Image.new("RGB", (300, 600), "white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()

    async def swipe(self, x1, y1, x2, y2, duration_ms=300, pause=0.0):
        self.swipes.append((x1, y1, x2, y2, duration_ms, pause))


class ObstacleAction(FakeAction):
    async def screenshot(self):
        self.screenshots += 1
        image = Image.new("RGB", (300, 600), "white")
        for x1 in (42, 122, 202):
            for x in range(x1, x1 + 56):
                for y in range(360, 500):
                    image.putpixel((x, y), (0, 0, 0))
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def test_fast_runner_records_loop_metrics(monkeypatch):
    reset_metrics()
    monkeypatch.setattr(config, "FAST_GAMEPLAY_SECONDS", 0.02, raising=False)
    monkeypatch.setattr(config, "FAST_GAMEPLAY_FRAME_DELAY", 0.01, raising=False)

    result = asyncio.run(FastRunnerGameplayScenario(None, FakeAction()).run())
    snapshot = metrics_snapshot()

    assert result is True
    assert snapshot["latencies"]["loop_total_ms"]["count"] >= 1
    assert snapshot["latencies"]["fps"]["count"] >= 1


def test_fast_runner_executes_gesture_path(monkeypatch):
    reset_metrics()
    monkeypatch.setattr(config, "FAST_GAMEPLAY_SECONDS", 0.01, raising=False)
    monkeypatch.setattr(config, "FAST_GAMEPLAY_FRAME_DELAY", 0.02, raising=False)
    action = ObstacleAction()

    result = asyncio.run(FastRunnerGameplayScenario(None, action).run())

    assert result is True
    assert action.swipes


def test_fast_runner_screen_size_fallbacks(monkeypatch):
    scenario = FastRunnerGameplayScenario(None, object())
    monkeypatch.setattr(config, "SCREEN_WIDTH", 111, raising=False)
    monkeypatch.setattr(config, "SCREEN_HEIGHT", 222, raising=False)

    assert scenario._screen_size() == (111, 222)

    class BadSizeAction:
        @property
        def _real_screen_w(self):
            raise RuntimeError("bad")

    assert FastRunnerGameplayScenario(None, BadSizeAction())._screen_size() == (111, 222)
