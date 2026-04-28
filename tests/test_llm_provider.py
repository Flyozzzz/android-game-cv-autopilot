import asyncio

from core.cv_engine import UIElement
from core.frame_source import Frame
from core.perception.providers.base import ProviderContext
from core.perception.providers.llm_provider import LLMProvider


class FakeCV:
    def __init__(self, element):
        self.element = element
        self.calls = []

    async def find_element(self, screenshot, target):
        self.calls.append((screenshot, target))
        return self.element


def _frame(png=b"\x89PNG\r\n\x1a\n" + b"0" * 64):
    return Frame(
        timestamp_ms=1,
        width=300,
        height=600,
        rgb_or_bgr_array=None,
        png_bytes=png,
        source_name="replay",
        latency_ms=0.0,
    )


def test_llm_provider_wraps_cv_engine_element():
    cv = FakeCV(UIElement(name="Continue", x=120, y=440, width=100, height=60, confidence=0.91, text="Continue"))
    provider = LLMProvider(cv)

    candidates = asyncio.run(
        provider.find(ProviderContext(frame=_frame(), goal="tap continue", screen_id="home"))
    )

    assert len(candidates) == 1
    assert candidates[0].name == "Continue"
    assert candidates[0].bbox == (70, 410, 170, 470)
    assert candidates[0].center == (120, 440)
    assert candidates[0].source == "llm"
    assert candidates[0].screen_id == "home"
    assert cv.calls[0][1] == "tap continue"


def test_llm_provider_filters_candidates_outside_roi():
    cv = FakeCV(UIElement(name="Continue", x=120, y=440, confidence=0.91))
    provider = LLMProvider(cv)

    candidates = asyncio.run(
        provider.find(ProviderContext(frame=_frame(), goal="continue", roi=(0, 0, 100, 100)))
    )

    assert candidates == []


def test_llm_provider_returns_empty_without_png_or_element():
    cv = FakeCV(None)
    provider = LLMProvider(cv)

    no_png = asyncio.run(provider.find(ProviderContext(frame=_frame(None), goal="continue")))
    no_element = asyncio.run(provider.find(ProviderContext(frame=_frame(), goal="continue")))

    assert no_png == []
    assert no_element == []
    assert len(cv.calls) == 1
