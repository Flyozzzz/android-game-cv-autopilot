import asyncio
from io import BytesIO

from PIL import Image

import config
from core.frame_source import Frame
from core.perception.defaults import (
    _load_template_registry,
    build_default_element_finder,
    reset_default_state_cache,
)


class FakeAction:
    async def get_visible_texts(self):
        return [("Continue", 20, 30)]


class FakeCV:
    async def find_element(self, screenshot, target):
        raise AssertionError("LLM fallback should not be called for confident local candidate")


def _frame() -> Frame:
    image = Image.new("RGB", (100, 100), "white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return Frame(
        timestamp_ms=1,
        width=100,
        height=100,
        rgb_or_bgr_array=None,
        png_bytes=buffer.getvalue(),
        source_name="replay",
        latency_ms=0.0,
    )


def test_default_element_finder_uses_enabled_uiautomator_provider(monkeypatch):
    reset_default_state_cache()
    monkeypatch.setattr(config, "PERCEPTION_MODE", "local_first")
    monkeypatch.setattr(config, "ENABLE_UIAUTOMATOR_PROVIDER", True)
    monkeypatch.setattr(config, "ENABLE_TEMPLATE_PROVIDER", False)
    monkeypatch.setattr(config, "ENABLE_DETECTOR_PROVIDER", False)
    monkeypatch.setattr(config, "ENABLE_LLM_FALLBACK", True)

    finder = build_default_element_finder(action=FakeAction(), cv=FakeCV())
    result = asyncio.run(finder.find(_frame(), goal="tap continue"))

    assert result.candidate.center == (20, 30)
    assert result.providers_called == ["uiautomator"]


def test_default_element_finder_wires_template_and_detector_providers(monkeypatch, tmp_path):
    reset_default_state_cache()
    registry = tmp_path / "registry.json"
    template = tmp_path / "button.png"
    image = Image.new("RGB", (4, 4), "white")
    image.save(template)
    registry.write_text(
        f"""
{{"templates": [{{
  "id": "play_button",
  "paths": ["{template}"],
  "threshold": 0.9
}}]}}
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "PERCEPTION_MODE", "local_only")
    monkeypatch.setattr(config, "ENABLE_UIAUTOMATOR_PROVIDER", False)
    monkeypatch.setattr(config, "ENABLE_TEMPLATE_PROVIDER", True)
    monkeypatch.setattr(config, "ENABLE_DETECTOR_PROVIDER", True)
    monkeypatch.setattr(config, "DETECTOR_MODEL_PATH", "", raising=False)
    monkeypatch.setattr(config, "DETECTOR_CONFIDENCE_THRESHOLD", 0.5, raising=False)
    monkeypatch.setattr(config, "ENABLE_LLM_FALLBACK", False)

    finder = build_default_element_finder(
        action=FakeAction(),
        cv=FakeCV(),
        template_registry_path=registry,
    )

    assert [provider.name for provider in finder.providers] == ["template", "detector"]
    assert finder.llm_provider is None


def test_default_template_registry_missing_is_optional(tmp_path):
    assert _load_template_registry(tmp_path / "missing.json") is None
