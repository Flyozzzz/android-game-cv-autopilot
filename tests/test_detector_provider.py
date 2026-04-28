import asyncio
from io import BytesIO
import sys
import types

from PIL import Image
import pytest

from core.frame_source import Frame
from core.perception.providers.base import ProviderContext
from core.perception.providers.detector_provider import (
    DetectorProvider,
    _input_hw,
    _parse_onnx_output,
)


def _png():
    buf = BytesIO()
    Image.new("RGB", (300, 600), "white").save(buf, format="PNG")
    return buf.getvalue()


def _context(roi=None, png="default"):
    return ProviderContext(
        frame=Frame(
            timestamp_ms=1,
            width=300,
            height=600,
            rgb_or_bgr_array=None,
            png_bytes=_png() if png == "default" else png,
            source_name="replay",
            latency_ms=0.0,
        ),
        goal="find object",
        roi=roi,
        screen_id="screen",
    )


def test_detector_provider_uses_injected_detector_callable():
    def detector(context):
        return [{"name": "coin", "bbox": [10, 20, 30, 40], "confidence": 0.91}]

    provider = DetectorProvider(detector=detector, threshold=0.5)

    candidates = asyncio.run(provider.find(_context()))

    assert len(candidates) == 1
    assert candidates[0].name == "coin"
    assert candidates[0].bbox == (10, 20, 30, 40)
    assert candidates[0].center == (20, 30)
    assert candidates[0].source == "detector"


def test_detector_provider_supports_async_detector_and_tuple_rows():
    async def detector(context):
        return [(50, 60, 90, 120, 0.88, 1)]

    provider = DetectorProvider(detector=detector, labels=["coin", "train"], threshold=0.5)

    candidates = asyncio.run(provider.find(_context()))

    assert len(candidates) == 1
    assert candidates[0].name == "train"
    assert candidates[0].confidence == 0.88


def test_detector_provider_filters_threshold_and_roi():
    def detector(context):
        return [
            {"name": "low", "bbox": [10, 20, 30, 40], "confidence": 0.3},
            {"name": "outside", "bbox": [200, 200, 230, 240], "confidence": 0.9},
            {"name": "inside", "bbox": [50, 50, 70, 70], "confidence": 0.9},
        ]

    provider = DetectorProvider(detector=detector, threshold=0.5)

    candidates = asyncio.run(provider.find(_context(roi=(0, 0, 100, 100))))

    assert [candidate.name for candidate in candidates] == ["inside"]


def test_detector_provider_is_empty_when_optional_backend_is_unavailable(tmp_path):
    provider = DetectorProvider(model_path=tmp_path / "missing.onnx")

    candidates = asyncio.run(provider.find(_context()))

    assert candidates == []
    assert provider._onnx_error == "model_not_found"


def test_detector_provider_without_model_path_returns_empty():
    provider = DetectorProvider()

    assert asyncio.run(provider.find(_context())) == []


def test_detector_provider_reports_onnxruntime_unavailable(monkeypatch, tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    monkeypatch.setitem(sys.modules, "onnxruntime", None)
    provider = DetectorProvider(model_path=model)

    candidates = asyncio.run(provider.find(_context()))

    assert candidates == []
    assert provider._onnx_error.startswith("onnxruntime_unavailable")


def test_detector_provider_runs_fake_onnx_session(monkeypatch, tmp_path):
    pytest.importorskip("numpy", exc_type=ImportError)
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")

    class FakeInput:
        name = "input"
        shape = [1, 3, 16, 16]

    class FakeSession:
        def get_inputs(self):
            return [FakeInput()]

        def run(self, names, feed):
            assert "input" in feed
            return [[
                [0.1, 0.2, 0.3, 0.4, 0.95, 0],
                [10, 20, 30, 40, 0.20, 0],
            ]]

    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        types.SimpleNamespace(InferenceSession=lambda path, providers: FakeSession()),
    )
    provider = DetectorProvider(model_path=model, labels=["coin"], threshold=0.5)

    candidates = asyncio.run(provider.find(_context()))

    assert len(candidates) == 1
    assert candidates[0].name == "coin"
    assert candidates[0].bbox == (30, 120, 90, 240)


def test_detector_provider_onnx_session_cache_and_no_png(monkeypatch, tmp_path):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"model")
    fake_session = object()
    monkeypatch.setitem(
        sys.modules,
        "onnxruntime",
        types.SimpleNamespace(InferenceSession=lambda path, providers: fake_session),
    )
    provider = DetectorProvider(model_path=model)

    assert provider._onnx_session() is fake_session
    assert provider._onnx_session() is fake_session
    assert asyncio.run(provider.find(_context(png=None))) == []


def test_detector_provider_run_onnx_handles_missing_numpy(monkeypatch):
    class FakeSession:
        pass

    monkeypatch.setitem(sys.modules, "numpy", None)
    provider = DetectorProvider()

    assert provider._run_onnx(FakeSession(), _context()) == []
    assert provider._onnx_error == "numpy_unavailable"


def test_detector_provider_parse_detection_box_alias_and_invalid_bbox():
    def detector(context):
        return [
            {"label": "box-alias", "box": [1, 2, 3, 4], "score": 2.0},
            {"name": "bad", "bbox": "bad", "confidence": 0.9},
        ]

    provider = DetectorProvider(detector=detector)

    candidates = asyncio.run(provider.find(_context()))

    assert len(candidates) == 1
    assert candidates[0].name == "box-alias"
    assert candidates[0].confidence == 1.0


def test_detector_provider_ignores_bad_detection_shapes():
    def detector(context):
        return [
            {"name": "bad", "bbox": [10, 20, 5, 30], "confidence": 0.9},
            ("too-short",),
            {"name": "ok", "bbox": [1, 2, 3, 4], "confidence": 0.9},
        ]

    provider = DetectorProvider(detector=detector)

    candidates = asyncio.run(provider.find(_context()))

    assert [candidate.name for candidate in candidates] == ["ok"]


def test_detector_provider_parse_onnx_output_and_input_shape_helpers():
    np = pytest.importorskip("numpy", exc_type=ImportError)

    invalid = _parse_onnx_output(np.zeros((2, 2, 2, 2)), 100, 100, [])
    parsed = _parse_onnx_output(
        np.array([[[0.1, 0.2, 0.3, 0.4, 0.9, 0]]]),
        100,
        200,
        ["coin"],
    )

    assert invalid == []
    assert parsed[0]["bbox"] == [10.0, 40.0, 30.0, 80.0]
    assert parsed[0]["name"] == "coin"
    assert _input_hw([1, 3, "height", None]) == (640, 640)
    assert _input_hw(None) == (640, 640)


def test_detector_provider_parse_onnx_output_handles_missing_numpy(monkeypatch):
    monkeypatch.setitem(sys.modules, "numpy", None)

    assert _parse_onnx_output([], 100, 100, []) == []
