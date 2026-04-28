import asyncio
from io import BytesIO
from pathlib import Path
import sys
import types

from PIL import Image, ImageDraw

from core.frame_source import Frame
from core.perception.providers.base import ProviderContext
from core.perception.providers.template_provider import (
    TemplateMatch,
    TemplateProvider,
    _best_match,
    _best_match_cv2,
    _best_match_pil,
    _dedupe_matches,
    _iou,
)
from core.perception.template_registry import TemplateRegistry, TemplateSpec


def _png(image: Image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def _frame(image: Image.Image) -> Frame:
    return Frame(
        timestamp_ms=1,
        width=image.width,
        height=image.height,
        rgb_or_bgr_array=None,
        png_bytes=_png(image),
        source_name="replay",
        latency_ms=0.1,
    )


def _template_file(tmp_path, name: str, image: Image.Image):
    path = tmp_path / name
    path.write_bytes(_png(image))
    return path


def test_template_provider_finds_exact_template_match(tmp_path):
    screen = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((30, 40, 39, 49), fill="red")
    template = Image.new("RGB", (10, 10), "red")
    template_path = _template_file(tmp_path, "red.png", template)
    registry = TemplateRegistry({
        "play_button": TemplateSpec(
            id="play_button",
            paths=(str(template_path),),
            threshold=0.99,
        )
    })
    provider = TemplateProvider(registry)

    candidates = asyncio.run(
        provider.find(ProviderContext(frame=_frame(screen), goal="tap play"))
    )

    assert len(candidates) == 1
    assert candidates[0].name == "play_button"
    assert candidates[0].bbox == (30, 40, 40, 50)
    assert candidates[0].center == (35, 45)
    assert candidates[0].confidence >= 0.99


def test_template_provider_respects_roi(tmp_path):
    screen = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((30, 40, 39, 49), fill="red")
    template_path = _template_file(tmp_path, "red.png", Image.new("RGB", (10, 10), "red"))
    provider = TemplateProvider(
        TemplateRegistry({
            "play_button": TemplateSpec(id="play_button", paths=(str(template_path),), threshold=0.99)
        })
    )

    outside = asyncio.run(
        provider.find(ProviderContext(frame=_frame(screen), goal="tap play", roi=(0, 0, 20, 20)))
    )
    inside = asyncio.run(
        provider.find(ProviderContext(frame=_frame(screen), goal="tap play", roi=(25, 35, 50, 60)))
    )

    assert outside == []
    assert len(inside) == 1
    assert inside[0].bbox == (30, 40, 40, 50)


def test_template_provider_supports_scaled_templates(tmp_path):
    screen = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((20, 20, 34, 34), fill="blue")
    template_path = _template_file(tmp_path, "blue.png", Image.new("RGB", (10, 10), "blue"))
    provider = TemplateProvider(
        TemplateRegistry({
            "blue_button": TemplateSpec(
                id="blue_button",
                paths=(str(template_path),),
                threshold=0.99,
                scales=(1.5,),
            )
        })
    )

    candidates = asyncio.run(
        provider.find(ProviderContext(frame=_frame(screen), goal="tap blue"))
    )

    assert len(candidates) == 1
    assert candidates[0].bbox == (20, 20, 35, 35)


def test_template_provider_negative_template_can_suppress_match(tmp_path):
    screen = Image.new("RGB", (80, 80), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((30, 40, 39, 49), fill="red")
    red_path = _template_file(tmp_path, "red.png", Image.new("RGB", (10, 10), "red"))
    provider = TemplateProvider(
        TemplateRegistry({
            "play_button": TemplateSpec(
                id="play_button",
                paths=(str(red_path),),
                threshold=0.99,
                negative_templates=("disabled_play_button",),
            ),
            "disabled_play_button": TemplateSpec(
                id="disabled_play_button",
                paths=(str(red_path),),
                threshold=0.99,
            ),
        })
    )

    candidates = asyncio.run(
        provider.find(ProviderContext(frame=_frame(screen), goal="tap play"))
    )

    assert candidates == []


def test_template_registry_loads_specs_from_file(tmp_path):
    template_path = _template_file(tmp_path, "red.png", Image.new("RGB", (10, 10), "red"))
    registry_path = tmp_path / "templates.json"
    registry_path.write_text(
        f"""
{{
  "templates": [
    {{
      "id": "play_button",
      "paths": ["{template_path}"],
      "threshold": 0.9,
      "scales": [1.0, 1.2],
      "tap_offset": [0.25, 0.75]
    }}
  ]
}}
""",
        encoding="utf-8",
    )

    registry = TemplateRegistry.from_file(registry_path)

    spec = registry.get("play_button")
    assert spec is not None
    assert spec.threshold == 0.9
    assert spec.scales == (1.0, 1.2)
    assert spec.tap_offset == (0.25, 0.75)


def test_template_registry_validates_specs_and_file_shapes(tmp_path):
    for payload in (
        {"paths": ["x.png"]},
        {"id": "missing-paths"},
    ):
        try:
            TemplateSpec.from_mapping(payload)
        except ValueError:
            pass
        else:
            raise AssertionError("invalid template spec should fail")

    spec = TemplateSpec.from_mapping({
        "id": "odd",
        "paths": ["missing.png"],
        "tapOffset": [0.1],
        "threshold": 2,
        "scales": [],
        "negativeTemplates": ["disabled"],
        "searchStep": 0,
    })
    assert spec.tap_offset == (0.5, 0.5)
    assert spec.threshold == 1.0
    assert spec.scales == (1.0,)
    assert spec.negative_templates == ("disabled",)
    assert spec.search_step == 1

    object_path = tmp_path / "single.json"
    object_path.write_text('{"id":"single","paths":["missing.png"]}', encoding="utf-8")
    assert TemplateRegistry.from_file(object_path).get("single") is not None

    bad_path = tmp_path / "bad.json"
    bad_path.write_text('"bad"', encoding="utf-8")
    try:
        TemplateRegistry.from_file(bad_path)
    except ValueError:
        pass
    else:
        raise AssertionError("bad registry shape should fail")

    assert TemplateRegistry({"odd": spec}).expanded_paths(spec) == []


def test_template_provider_returns_empty_without_png_and_skips_large_template(tmp_path):
    template_path = _template_file(tmp_path, "large.png", Image.new("RGB", (100, 100), "red"))
    provider = TemplateProvider(
        TemplateRegistry({
            "large": TemplateSpec(id="large", paths=(str(template_path),), threshold=0.99)
        })
    )
    empty = asyncio.run(
        provider.find(ProviderContext(frame=Frame(1, 10, 10, None, None, "test", 0), goal="large"))
    )
    too_large = asyncio.run(
        provider.find(ProviderContext(frame=_frame(Image.new("RGB", (20, 20), "white")), goal="large"))
    )

    assert empty == []
    assert too_large == []


def test_template_provider_handles_missing_negative_spec(tmp_path):
    screen = Image.new("RGB", (30, 30), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((5, 5, 14, 14), fill="red")
    template_path = _template_file(tmp_path, "red.png", Image.new("RGB", (10, 10), "red"))
    provider = TemplateProvider(
        TemplateRegistry({
            "button": TemplateSpec(
                id="button",
                paths=(str(template_path),),
                threshold=0.99,
                negative_templates=("missing",),
            )
        })
    )

    candidates = asyncio.run(provider.find(ProviderContext(frame=_frame(screen), goal="button")))

    assert len(candidates) == 1


def test_template_matching_pil_fallback_and_helpers(monkeypatch):
    monkeypatch.setitem(sys.modules, "cv2", None)
    screen = Image.new("RGB", (20, 20), "white")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((5, 5, 9, 9), fill="black")
    template = Image.new("RGB", (5, 5), "black")

    assert _best_match_cv2(screen, template) is None
    assert _best_match(screen, template, step=2).bbox == (4, 4, 9, 9)
    match = _best_match_pil(screen, template, step=2)

    assert match.bbox == (4, 4, 9, 9)
    assert match.confidence > 0.6
    assert _iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert _iou((0, 0, 0, 0), (1, 1, 1, 1)) == 0.0
    deduped = _dedupe_matches([
        TemplateMatch((0, 0, 10, 10), 0.8, Path("a.png")),
        TemplateMatch((1, 1, 11, 11), 0.9, Path("b.png")),
    ])
    assert len(deduped) == 1


def test_template_matching_cv2_path_can_be_exercised(monkeypatch):
    fake_cv2 = types.SimpleNamespace(
        COLOR_RGB2BGR=1,
        TM_SQDIFF_NORMED=2,
        cvtColor=lambda arr, code: arr,
        matchTemplate=lambda screen, template, mode: "result",
        minMaxLoc=lambda result: (0.25, 0.0, (3, 4), (0, 0)),
    )
    fake_np = types.SimpleNamespace(array=lambda value: value)
    monkeypatch.setitem(sys.modules, "cv2", fake_cv2)
    monkeypatch.setitem(sys.modules, "numpy", fake_np)

    match = _best_match_cv2(Image.new("RGB", (20, 20)), Image.new("RGB", (5, 6)))

    assert match.bbox == (3, 4, 8, 10)
    assert match.confidence == 0.75
