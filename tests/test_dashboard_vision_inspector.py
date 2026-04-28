from core.metrics import TraceEvent, record_trace, reset_metrics
from dashboard.api_vision import vision_inspector_payload


def test_vision_inspector_payload_uses_latest_trace_and_metrics():
    reset_metrics()
    record_trace(
        TraceEvent(
            run_id="run-1",
            profile_id="profile",
            screen_id="home",
            frame_source="replay",
            goal="tap continue",
            roi={"pixel_box": (1, 2, 3, 4)},
            providers_called=["template", "llm"],
            candidates=[{"name": "Continue", "bbox": (10, 20, 50, 60), "confidence": 0.9}],
            selected_candidate={"name": "Continue", "source": "template", "confidence": 0.9},
            latency_breakdown={"provider_template_ms": 4.2},
            llm_called=True,
        )
    )

    payload = vision_inspector_payload(serial="emu 1")

    assert payload["frame"]["source"] == "replay"
    assert payload["frame"]["screenshotUrl"] == "/api/device/screenshot?serial=emu%201"
    assert payload["overlay"]["roi"] == {"pixel_box": (1, 2, 3, 4)}
    assert payload["overlay"]["selectedCandidate"]["name"] == "Continue"
    assert payload["decision"]["providersCalled"] == ["template", "llm"]
    assert payload["decision"]["llmCalled"] is True
    assert payload["latency"] == {"provider_template_ms": 4.2}


def test_vision_inspector_payload_has_safe_empty_shape_without_trace():
    reset_metrics()

    payload = vision_inspector_payload()

    assert payload["frame"]["screenshotUrl"] == "/api/device/screenshot"
    assert payload["overlay"]["candidates"] == []
    assert payload["decision"]["providersCalled"] == []
    assert payload["decision"]["llmCalled"] is False
