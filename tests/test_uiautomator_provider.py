import asyncio

from core.frame_source import Frame
from core.perception.providers.base import ProviderContext
from core.perception.providers.uiautomator_provider import UIAutomatorProvider


class FakeAction:
    def __init__(self, texts):
        self.texts = texts
        self.calls = 0

    async def get_visible_texts(self):
        self.calls += 1
        return self.texts


def _context(goal: str, roi=None):
    return ProviderContext(
        frame=Frame(
            timestamp_ms=1,
            width=300,
            height=600,
            rgb_or_bgr_array=None,
            png_bytes=None,
            source_name="test",
            latency_ms=0.0,
        ),
        goal=goal,
        roi=roi,
        screen_id="screen",
    )


def test_uiautomator_provider_matches_visible_text_goal():
    action = FakeAction([("Cancel", 50, 550), ("Continue", 160, 520)])
    provider = UIAutomatorProvider(action)

    candidates = asyncio.run(provider.find(_context("tap continue")))

    assert len(candidates) == 1
    assert candidates[0].name == "Continue"
    assert candidates[0].center == (160, 520)
    assert candidates[0].confidence == 0.86
    assert candidates[0].source == "uiautomator"
    assert action.calls == 1


def test_uiautomator_provider_filters_by_roi():
    action = FakeAction([("Continue", 160, 520), ("Continue", 160, 120)])
    provider = UIAutomatorProvider(action)

    candidates = asyncio.run(provider.find(_context("continue", roi=(0, 400, 300, 600))))

    assert len(candidates) == 1
    assert candidates[0].center == (160, 520)


def test_uiautomator_provider_accepts_dict_visible_texts():
    action = FakeAction([{"text": "Allow", "cx": 200, "cy": 500}])
    provider = UIAutomatorProvider(action)

    candidates = asyncio.run(provider.find(_context("allow permission")))

    assert len(candidates) == 1
    assert candidates[0].text == "Allow"


def test_uiautomator_provider_returns_empty_without_action_support():
    provider = UIAutomatorProvider(object())

    candidates = asyncio.run(provider.find(_context("continue")))

    assert candidates == []


def test_uiautomator_provider_ignores_bad_visible_text_rows():
    action = FakeAction([("Continue", "bad", 520), ("", 1, 2), ("OK", 20, 30)])
    provider = UIAutomatorProvider(action)

    candidates = asyncio.run(provider.find(_context("ok")))

    assert len(candidates) == 1
    assert candidates[0].name == "OK"


def test_uiautomator_provider_ignores_unknown_row_shapes():
    action = FakeAction(["plain text", {"text": "OK", "x": "bad", "y": 1}, {"label": "Allow", "x": 10, "y": 20}])
    provider = UIAutomatorProvider(action)

    candidates = asyncio.run(provider.find(_context("")))

    assert len(candidates) == 1
    assert candidates[0].name == "Allow"
