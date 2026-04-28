from core.perception.element import ElementCandidate
from core.perception.fusion import FusionConfig, FusionEngine


def test_fusion_prefers_text_and_roi_match_over_raw_confidence_gap():
    outside = ElementCandidate.from_bbox(
        name="decorative banner",
        bbox=(500, 500, 700, 600),
        confidence=0.80,
        source="template",
    )
    inside_text = ElementCandidate.from_bbox(
        name="Continue button",
        bbox=(100, 100, 200, 160),
        confidence=0.70,
        source="ocr",
        text="Continue",
    )

    ranked = FusionEngine().rank(
        [outside, inside_text],
        goal="tap continue",
        roi=(80, 80, 240, 200),
    )

    assert ranked[0].candidate.name == "Continue button"
    assert "roi" in ranked[0].reasons
    assert "text" in ranked[0].reasons


def test_fusion_applies_source_priority_and_recency():
    old = ElementCandidate.from_bbox(
        name="Play",
        bbox=(10, 10, 50, 50),
        confidence=0.76,
        source="ocr",
    )
    recent_template = ElementCandidate.from_bbox(
        name="Play",
        bbox=(10, 10, 50, 50),
        confidence=0.72,
        source="template",
        screen_id="home",
    )
    fusion = FusionEngine(
        FusionConfig(source_priorities={"template": 0.1}, recency_bonus=0.05)
    )

    ranked = fusion.rank([old, recent_template], goal="play", recent_screen_ids={"home"})

    assert ranked[0].candidate.source == "template"
    assert "source_priority:template" in ranked[0].reasons
    assert "recency" in ranked[0].reasons


def test_fusion_covers_stale_penalty_and_no_text_match_paths():
    candidate = ElementCandidate.from_bbox(
        name="",
        bbox=(0, 0, 10, 10),
        confidence=0.5,
        source="template",
    )
    fusion = FusionEngine(FusionConfig(stale_frame_penalty=0.1))

    ranked = fusion.rank([candidate], goal="", roi=(20, 20, 40, 40))

    assert ranked[0].score == 0.4
    assert "stale_penalty" in ranked[0].reasons

    no_haystack = FusionEngine().rank([candidate], goal="continue")
    assert no_haystack[0].score == 0.5
