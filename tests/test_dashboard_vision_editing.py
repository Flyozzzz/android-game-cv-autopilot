import base64
from io import BytesIO
import json

from PIL import Image, ImageDraw

from dashboard.api_vision import (
    TEMPLATES_ROOT,
    create_roi_from_payload,
    export_label_from_payload,
    list_template_library,
    save_template_from_payload,
    _template_glob_path,
)


def _png() -> bytes:
    image = Image.new("RGB", (100, 100), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 30, 39, 49), fill="red")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


def test_save_template_crops_image_and_updates_registry(tmp_path):
    result = save_template_from_payload(
        {
            "templateId": "Play Button",
            "namespace": "Common",
            "bbox": [20, 30, 40, 50],
            "screenshotBase64": base64.b64encode(_png()).decode(),
            "threshold": 0.9,
        },
        templates_root=tmp_path,
    )

    saved_path = tmp_path / "common" / "play-button"
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))

    assert result["saved"] is True
    assert result["templateId"] == "play-button"
    assert result["size"] == [20, 20]
    assert len(list(saved_path.glob("*.png"))) == 1
    assert registry["templates"][0]["id"] == "play-button"
    assert registry["templates"][0]["threshold"] == 0.9


def test_save_template_accepts_data_url_and_replaces_existing_registry_spec(tmp_path):
    encoded = "data:image/png;base64," + base64.b64encode(_png()).decode()
    payload = {
        "id": "play",
        "profileId": "game",
        "bbox": [20, 30, 40, 50],
        "imageBase64": encoded,
    }

    first = save_template_from_payload(payload, templates_root=tmp_path)
    second = save_template_from_payload(payload, templates_root=tmp_path)
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))

    assert first["templateId"] == "play"
    assert second["namespace"] == "game"
    assert len(registry["templates"]) == 1


def test_save_template_rejects_missing_image_and_bad_bbox(tmp_path):
    try:
        save_template_from_payload({"templateId": "x", "bbox": [1, 2, 3, 4]}, templates_root=tmp_path)
    except RuntimeError as exc:
        assert "screenshot" in str(exc)
    else:
        raise AssertionError("missing screenshot should fail")

    try:
        save_template_from_payload(
            {"templateId": "x", "bbox": [4, 2, 3, 4], "screenshotBase64": base64.b64encode(_png()).decode()},
            templates_root=tmp_path,
        )
    except RuntimeError as exc:
        assert "x2>x1" in str(exc)
    else:
        raise AssertionError("bad bbox should fail")

    try:
        save_template_from_payload(
            {"templateId": "x", "bbox": [1, 2, 3], "screenshotBase64": base64.b64encode(_png()).decode()},
            templates_root=tmp_path,
        )
    except RuntimeError as exc:
        assert "bbox" in str(exc)
    else:
        raise AssertionError("malformed bbox should fail")


def test_save_template_recovers_from_bad_registry_shape(tmp_path):
    (tmp_path / "registry.json").write_text('"bad"', encoding="utf-8")

    save_template_from_payload(
        {
            "templateId": "play",
            "namespace": "common",
            "bbox": [20, 30, 40, 50],
            "screenshotBase64": base64.b64encode(_png()).decode(),
        },
        templates_root=tmp_path,
    )
    registry = json.loads((tmp_path / "registry.json").read_text(encoding="utf-8"))

    assert registry["templates"][0]["id"] == "play"


def test_list_template_library_reads_registry_and_files(tmp_path):
    save_template_from_payload(
        {
            "templateId": "play",
            "namespace": "common",
            "bbox": [20, 30, 40, 50],
            "screenshotBase64": base64.b64encode(_png()).decode(),
            "roi": "bottom_buttons",
        },
        templates_root=tmp_path,
    )

    result = list_template_library(templates_root=tmp_path)

    assert result["total"] == 1
    assert result["templates"][0]["id"] == "play"
    assert result["templates"][0]["namespace"] == "common"
    assert result["templates"][0]["roi"] == "bottom_buttons"
    assert result["templates"][0]["fileCount"] == 1
    assert result["templates"][0]["files"][0].endswith(".png")


def test_list_template_library_handles_missing_or_bad_registry(tmp_path):
    assert list_template_library(templates_root=tmp_path)["templates"] == []

    (tmp_path / "registry.json").write_text('"bad"', encoding="utf-8")
    assert list_template_library(templates_root=tmp_path)["templates"] == []


def test_create_roi_updates_custom_profile_json(tmp_path):
    result = create_roi_from_payload(
        {
            "profileId": "custom-game",
            "zoneName": "Bottom Buttons",
            "pixelBox": [10, 70, 90, 95],
            "width": 100,
            "height": 100,
        },
        profiles_root=tmp_path,
    )
    data = json.loads((tmp_path / "custom-game.json").read_text(encoding="utf-8"))

    assert result["saved"] is True
    assert result["zoneName"] == "bottom-buttons"
    assert data["screen_zones"]["bottom-buttons"] == [0.1, 0.7, 0.9, 0.95]


def test_create_roi_can_start_from_builtin_profile(tmp_path):
    result = create_roi_from_payload(
        {
            "profileId": "subway-surfers",
            "zoneName": "new zone",
            "normalizedBox": [0.2, 0.3, 0.8, 0.9],
        },
        profiles_root=tmp_path,
    )
    data = json.loads((tmp_path / "subway-surfers.json").read_text(encoding="utf-8"))

    assert result["saved"] is True
    assert data["package"] == "com.kiloo.subwaysurf"
    assert data["screen_zones"]["new-zone"] == [0.2, 0.3, 0.8, 0.9]


def test_create_roi_rejects_invalid_payloads(tmp_path):
    for payload in (
        {"profileId": "x", "zoneName": "z", "bbox": [1, 2, 3, 4]},
        {"profileId": "x", "zoneName": "z", "normalizedBox": [0.9, 0.2, 0.1, 0.8]},
        {"profileId": "", "zoneName": "z", "normalizedBox": [0.1, 0.2, 0.3, 0.4]},
    ):
        try:
            create_roi_from_payload(payload, profiles_root=tmp_path)
        except RuntimeError:
            pass
        else:
            raise AssertionError("invalid ROI payload should fail")


def test_create_roi_preserves_existing_profile_fields(tmp_path):
    path = tmp_path / "custom-game.json"
    path.write_text(
        json.dumps({"id": "custom-game", "name": "Custom Game", "package": "pkg", "screen_zones": {}}),
        encoding="utf-8",
    )

    create_roi_from_payload(
        {
            "profileId": "custom-game",
            "zoneName": "popup",
            "normalizedBox": [0.1, 0.2, 0.8, 0.9],
        },
        profiles_root=tmp_path,
    )
    data = json.loads(path.read_text(encoding="utf-8"))

    assert data["name"] == "Custom Game"
    assert data["screen_zones"]["popup"] == [0.1, 0.2, 0.8, 0.9]


def test_export_label_writes_label_json(tmp_path):
    result = export_label_from_payload(
        {
            "profileId": "game",
            "labelId": "Continue",
            "goal": "tap continue",
            "candidate": {"name": "Continue", "bbox": [1, 2, 3, 4]},
        },
        labels_root=tmp_path,
    )
    label_path = tmp_path / result["path"].split("/")[-1]
    data = json.loads(label_path.read_text(encoding="utf-8"))

    assert result["saved"] is True
    assert data["profile_id"] == "game"
    assert data["label_id"] == "continue"
    assert data["candidate"]["name"] == "Continue"


def test_export_label_rejects_missing_candidate(tmp_path):
    try:
        export_label_from_payload({"profileId": "game"}, labels_root=tmp_path)
    except RuntimeError as exc:
        assert "candidate" in str(exc)
    else:
        raise AssertionError("missing candidate should fail")


def test_template_glob_path_for_default_root_is_repo_relative():
    path = _template_glob_path(TEMPLATES_ROOT, "common", "play")

    assert path == "assets/templates/common/play/*.png"

    class BadRoot:
        def __truediv__(self, other):
            return self

        def resolve(self):
            raise RuntimeError("bad root")

        def __str__(self):
            return "bad-root"

    assert _template_glob_path(BadRoot(), "common", "play") == "bad-root"
