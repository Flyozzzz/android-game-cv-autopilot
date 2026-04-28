import asyncio
from io import BytesIO

from PIL import Image, ImageDraw

import config
import scenarios.match3_gameplay as match3_gameplay
from core.perception.screen_stability import StabilityResult
from scenarios.match3_gameplay import Match3GameplayScenario


class FakeAction:
    def __init__(self, screenshot: bytes):
        self._screenshot = screenshot
        self.screenshot_calls = 0
        self.swipes = []

    async def screenshot(self) -> bytes:
        self.screenshot_calls += 1
        return self._screenshot

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> None:
        self.swipes.append((x1, y1, x2, y2, duration_ms))


def _board_png() -> bytes:
    image = Image.new("RGB", (300, 300), "white")
    draw = ImageDraw.Draw(image)
    board = [
        ["red", "blue", "red"],
        ["blue", "red", "blue"],
        ["green", "green", "blue"],
    ]
    rgb = {"red": (240, 20, 20), "green": (20, 220, 20), "blue": (20, 20, 240)}
    for row_index, row in enumerate(board):
        for col_index, color in enumerate(row):
            draw.rectangle(
                (
                    col_index * 100,
                    row_index * 100,
                    col_index * 100 + 99,
                    row_index * 100 + 99,
                ),
                fill=rgb[color],
            )
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _solid_board_png() -> bytes:
    image = Image.new("RGB", (300, 300), "red")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _configure_match3(monkeypatch) -> None:
    monkeypatch.setattr(config, "MATCH3_GRID_ROWS", 3, raising=False)
    monkeypatch.setattr(config, "MATCH3_GRID_COLS", 3, raising=False)
    monkeypatch.setattr(config, "MATCH3_MAX_MOVES", 1, raising=False)
    monkeypatch.setattr(config, "MATCH3_GRID_BOUNDS", "0,0,300,300", raising=False)
    monkeypatch.setattr(config, "MATCH3_STABILITY_ENABLED", True, raising=False)
    monkeypatch.setattr(config, "MATCH3_STABILITY_TIMEOUT_MS", 1, raising=False)
    monkeypatch.setattr(config, "MATCH3_STABILITY_POLL_MS", 0, raising=False)


def test_match3_waits_for_stable_board_before_swiping(monkeypatch):
    _configure_match3(monkeypatch)
    calls = []

    async def fake_wait_until_stable(frame_source, **kwargs):
        calls.append((frame_source, kwargs))
        return StabilityResult(True, "stable", 2, 0.0, 2.5)

    async def fake_sleep(_seconds):
        return None

    monkeypatch.setattr(match3_gameplay, "wait_until_stable", fake_wait_until_stable)
    monkeypatch.setattr(match3_gameplay.asyncio, "sleep", fake_sleep)
    action = FakeAction(_board_png())

    result = asyncio.run(Match3GameplayScenario(None, action).run())

    assert result is True
    assert calls
    assert calls[0][1]["roi"] == (0, 0, 300, 300)
    assert len(action.swipes) == 1
    assert action.screenshot_calls == 1


def test_match3_skips_move_when_board_is_not_stable(monkeypatch):
    _configure_match3(monkeypatch)

    async def fake_wait_until_stable(frame_source, **kwargs):
        return StabilityResult(False, "timeout", 2, 42.0, 2.5)

    monkeypatch.setattr(match3_gameplay, "wait_until_stable", fake_wait_until_stable)
    action = FakeAction(_board_png())

    result = asyncio.run(Match3GameplayScenario(None, action).run())

    assert result is True
    assert action.swipes == []
    assert action.screenshot_calls == 0


def test_match3_stops_when_no_swap_exists(monkeypatch):
    _configure_match3(monkeypatch)

    async def fake_wait_until_stable(frame_source, **kwargs):
        return StabilityResult(True, "stable", 2, 0.0, 2.5)

    monkeypatch.setattr(match3_gameplay, "wait_until_stable", fake_wait_until_stable)
    action = FakeAction(_solid_board_png())

    result = asyncio.run(Match3GameplayScenario(None, action).run())

    assert result is True
    assert action.swipes == []
    assert action.screenshot_calls == 1


def test_match3_bounds_config_validation(monkeypatch):
    monkeypatch.setattr(config, "MATCH3_GRID_BOUNDS", "", raising=False)
    assert Match3GameplayScenario._bounds_from_config() is None

    monkeypatch.setattr(config, "MATCH3_GRID_BOUNDS", "1,2,3", raising=False)
    try:
        Match3GameplayScenario._bounds_from_config()
    except RuntimeError as exc:
        assert "x1,y1,x2,y2" in str(exc)
    else:
        raise AssertionError("expected invalid bounds error")

    monkeypatch.setattr(config, "MATCH3_GRID_BOUNDS", "1,2,x,4", raising=False)
    try:
        Match3GameplayScenario._bounds_from_config()
    except RuntimeError as exc:
        assert "integers" in str(exc)
    else:
        raise AssertionError("expected integer bounds error")

    monkeypatch.setattr(config, "MATCH3_GRID_BOUNDS", "4,2,1,3", raising=False)
    try:
        Match3GameplayScenario._bounds_from_config()
    except RuntimeError as exc:
        assert "x2>x1" in str(exc)
    else:
        raise AssertionError("expected ordered bounds error")
