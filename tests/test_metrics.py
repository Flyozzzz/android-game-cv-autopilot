import asyncio

from core.action_engine import ActionEngine
from core.cv_engine import CVEngine, _normalize_ui_action
from core.metrics import MetricsCollector, TraceEvent, reset_metrics, metrics_snapshot


def _png(width: int = 16, height: int = 24) -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + b"\x00\x00\x00\rIHDR"
        + width.to_bytes(4, "big")
        + height.to_bytes(4, "big")
        + b"\x08\x02\x00\x00\x00"
        + b"0" * 128
    )


def test_metrics_collector_records_timer_and_trace_event():
    collector = MetricsCollector(max_events=3)

    with collector.timer("capture_ms"):
        pass
    collector.record_latency("custom_ms", 1.23)
    collector.record_trace(
        TraceEvent(
            run_id="run-1",
            profile_id="subway-surfers",
            screen_id="home",
            frame_source="adb",
            goal="tap play",
            providers_called=["template"],
            candidates=[{"name": "play", "confidence": 0.91}],
            selected_candidate={"name": "play", "source": "template"},
            action={"type": "tap", "x": 100, "y": 200},
            policy_result="allowed",
            latency_breakdown={"provider_template_ms": 4.2},
            llm_called=False,
        )
    )

    snapshot = collector.snapshot()

    assert snapshot["latencies"]["capture_ms"]["count"] == 1
    assert snapshot["latencies"]["custom_ms"]["last_ms"] == 1.23
    assert snapshot["latest_trace"]["run_id"] == "run-1"
    assert snapshot["latest_trace"]["providers_called"] == ["template"]


def test_action_engine_records_capture_and_action_metrics():
    class FakeActionEngine(ActionEngine):
        def __init__(self):
            super().__init__("device-1")
            self.commands = []

        async def _run_adb_raw(self, *args, timeout=None):
            self.commands.append(args)
            return _png()

        async def _run_adb(self, *args, timeout=None):
            self.commands.append(args)
            return "ok"

    reset_metrics()
    action = FakeActionEngine()

    screenshot = asyncio.run(action.screenshot())
    asyncio.run(action.tap(10, 20, pause=0))
    asyncio.run(action.swipe(1, 2, 3, 4, duration_ms=90))

    snapshot = metrics_snapshot()

    assert screenshot.startswith(b"\x89PNG\r\n\x1a\n")
    assert action._real_screen_w == 16
    assert action._real_screen_h == 24
    assert snapshot["latencies"]["capture_ms"]["count"] == 1
    assert snapshot["latencies"]["action_ms"]["count"] == 2


def test_cv_engine_records_llm_provider_latency():
    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": "{\"ok\": true}"}}]}

    class FakeClient:
        def __init__(self):
            self.max_tokens = None

        async def post(self, *args, **kwargs):
            self.max_tokens = kwargs["json"]["max_tokens"]
            return FakeResponse()

        async def aclose(self):
            pass

    reset_metrics()
    cv = CVEngine(api_key="key", models=["test/model"])
    client = FakeClient()
    cv.client = client

    result = asyncio.run(cv._call_vision("find button", "a" * 120))
    asyncio.run(cv.close())
    snapshot = metrics_snapshot()

    assert result == "{\"ok\": true}"
    assert client.max_tokens == 4096
    assert snapshot["counters"]["provider_llm_calls"] == 1
    assert snapshot["latencies"]["provider_llm_ms"]["count"] == 1


def test_cv_engine_retries_empty_openrouter_content(monkeypatch):
    class FakeResponse:
        status_code = 200
        text = "{}"

        def __init__(self, content):
            self.content = content

        def json(self):
            return {"choices": [{"message": {"content": self.content}}]}

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def post(self, *args, **kwargs):
            self.calls += 1
            return FakeResponse(None if self.calls == 1 else "{\"ok\": true}")

        async def aclose(self):
            pass

    monkeypatch.setattr("config.CV_MODEL_ATTEMPTS", 2)
    client = FakeClient()
    cv = CVEngine(api_key="key", models=["test/model"])
    cv.client = client

    result = asyncio.run(cv._call_vision("find button", "a" * 120))
    asyncio.run(cv.close())

    assert result == "{\"ok\": true}"
    assert client.calls == 2


def test_cv_engine_accepts_openrouter_content_parts():
    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {"choices": [{"message": {"content": [{"text": "{\"ok\":"}, {"text": " true}"}]}}]}

    class FakeClient:
        async def post(self, *args, **kwargs):
            return FakeResponse()

        async def aclose(self):
            pass

    cv = CVEngine(api_key="key", models=["test/model"])
    cv.client = FakeClient()

    result = asyncio.run(cv._call_vision("find button", "a" * 120))
    asyncio.run(cv.close())

    assert result == "{\"ok\":\n true}"


def test_cv_engine_normalizes_common_vision_action_aliases():
    assert _normalize_ui_action("click") == "tap"
    assert _normalize_ui_action("input") == "type"
    assert _normalize_ui_action("key") == "press"
    assert _normalize_ui_action("scroll") == "swipe"


def test_cv_engine_rejects_missing_api_key_before_http(monkeypatch):
    class FailingClient:
        async def post(self, *args, **kwargs):
            raise AssertionError("HTTP must not be called without API key")

        async def aclose(self):
            pass

    monkeypatch.setattr("config.OPENROUTER_API_KEY", "")
    cv = CVEngine(api_key="", models=["test/model"])
    cv.client = FailingClient()

    try:
        asyncio.run(cv._call_vision("find button", "a" * 120))
    except RuntimeError as exc:
        assert "Vision API key is required" in str(exc)
    else:
        raise AssertionError("missing API key should fail")
    finally:
        asyncio.run(cv.close())
