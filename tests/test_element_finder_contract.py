import asyncio
from io import BytesIO

from PIL import Image

from core.frame_source import Frame
from core.metrics import metrics_snapshot, reset_metrics
from core.perception.element import ElementCandidate
from core.perception.finder import ElementFinder, _metric_name
from core.perception.state_cache import ScreenStateCache


class FakeProvider:
    def __init__(self, name, candidates):
        self.name = name
        self.candidates = list(candidates)
        self.calls = 0

    async def find(self, context):
        self.calls += 1
        return self.candidates


def _frame() -> Frame:
    return Frame(
        timestamp_ms=1,
        width=300,
        height=600,
        rgb_or_bgr_array=None,
        png_bytes=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
        source_name="replay",
        latency_ms=0.1,
    )


def _png_frame() -> Frame:
    image = Image.new("RGB", (32, 32), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Frame(
        timestamp_ms=1,
        width=32,
        height=32,
        rgb_or_bgr_array=None,
        png_bytes=buffer.getvalue(),
        source_name="replay",
        latency_ms=0.1,
    )


def _candidate(name, confidence, source):
    return ElementCandidate.from_bbox(
        name=name,
        bbox=(10, 10, 110, 70),
        confidence=confidence,
        source=source,
        text=name,
    )


def test_element_finder_local_first_uses_local_candidate_above_threshold():
    template = FakeProvider("template", [_candidate("Continue", 0.90, "template")])
    llm = FakeProvider("llm", [_candidate("Continue", 0.95, "llm")])
    finder = ElementFinder([template], llm_provider=llm, mode="local_first", min_confidence=0.65)

    result = asyncio.run(finder.find(_frame(), goal="tap continue", roi=(0, 0, 200, 200)))

    assert result.found is True
    assert result.candidate.source == "template"
    assert result.providers_called == ["template"]
    assert result.llm_called is False
    assert template.calls == 1
    assert llm.calls == 0


def test_element_finder_local_first_falls_back_to_llm_below_threshold():
    template = FakeProvider("template", [_candidate("Maybe continue", 0.40, "template")])
    llm = FakeProvider("llm", [_candidate("Continue", 0.92, "llm")])
    finder = ElementFinder([template], llm_provider=llm, mode="local_first", min_confidence=0.65)

    result = asyncio.run(finder.find(_frame(), goal="tap continue"))

    assert result.candidate.source == "llm"
    assert result.providers_called == ["template", "llm"]
    assert result.llm_called is True
    assert llm.calls == 1


def test_element_finder_local_only_never_calls_llm():
    template = FakeProvider("template", [])
    llm = FakeProvider("llm", [_candidate("Continue", 0.92, "llm")])
    finder = ElementFinder([template], llm_provider=llm, mode="local_only")

    result = asyncio.run(finder.find(_frame(), goal="tap continue"))

    assert result.found is False
    assert result.llm_called is False
    assert llm.calls == 0


def test_element_finder_shadow_calls_llm_but_keeps_local_candidates_in_trace():
    reset_metrics()
    template = FakeProvider("template", [_candidate("Continue local", 0.99, "template")])
    llm = FakeProvider("llm", [_candidate("Continue llm", 0.70, "llm")])
    finder = ElementFinder([template], llm_provider=llm, mode="shadow")

    result = asyncio.run(
        finder.find(_frame(), goal="tap continue", screen_id="home", profile_id="profile")
    )
    snapshot = metrics_snapshot()

    assert result.candidate.source == "llm"
    assert result.llm_called is True
    assert result.providers_called == ["template", "llm"]
    assert snapshot["latest_trace"]["providers_called"] == ["template", "llm"]
    assert len(snapshot["latest_trace"]["candidates"]) == 2


def test_element_finder_llm_first_uses_only_llm_when_enabled():
    template = FakeProvider("template", [_candidate("Continue local", 0.99, "template")])
    llm = FakeProvider("llm", [_candidate("Continue llm", 0.70, "llm")])
    finder = ElementFinder([template], llm_provider=llm, mode="llm_first")

    result = asyncio.run(finder.find(_frame(), goal="tap continue"))

    assert result.candidate.source == "llm"
    assert result.providers_called == ["llm"]
    assert template.calls == 0
    assert llm.calls == 1


def test_element_finder_handles_no_provider_and_disabled_llm_fallback():
    finder = ElementFinder([], llm_provider=None, mode="local_first", enable_llm_fallback=False)

    result = asyncio.run(finder.find(_frame(), goal="missing"))

    assert result.found is False
    assert result.ranked_candidates == []
    assert finder._select_candidate([], llm_called=False) is None
    assert asyncio.run(finder._run_provider(None, None)) == ([], 0.0)
    unknown_mode = ElementFinder([], llm_provider=FakeProvider("llm", []), mode="unknown")
    assert unknown_mode._should_call_llm(None) is False
    assert _metric_name("") == "provider_unknown_ms"


def test_element_finder_reuses_screen_state_cache_before_providers():
    frame = _png_frame()
    template = FakeProvider("template", [_candidate("Continue", 0.90, "template")])
    llm = FakeProvider("llm", [_candidate("Continue", 0.95, "llm")])
    cache = ScreenStateCache(hamming_threshold=0)
    finder = ElementFinder(
        [template],
        llm_provider=llm,
        mode="local_first",
        state_cache=cache,
    )

    first = asyncio.run(finder.find(frame, goal="tap continue", screen_id="home"))
    second = asyncio.run(finder.find(frame, goal="tap continue", screen_id="home"))

    assert first.candidate.source == "template"
    assert second.candidate.source == "template"
    assert second.providers_called == ["cache"]
    assert template.calls == 1
    assert llm.calls == 0
