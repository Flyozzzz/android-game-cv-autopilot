import pytest

from core.game_profiles import resolve_game_profile
from core.perception.roi import ROISelector, normalized_to_pixels, validate_normalized_box


def test_normalized_to_pixels_scales_percent_zones_to_resolution():
    assert normalized_to_pixels((0.1, 0.2, 0.9, 0.8), width=1000, height=2000) == (
        100,
        400,
        900,
        1600,
    )


def test_normalized_box_validation_rejects_invalid_coordinates():
    with pytest.raises(ValueError):
        validate_normalized_box((0.1, 0.2, 0.3))

    with pytest.raises(ValueError):
        validate_normalized_box((0.9, 0.2, 0.1, 0.8))

    with pytest.raises(ValueError):
        normalized_to_pixels((0.1, 0.2, 1.2, 0.8), width=100, height=100)

    with pytest.raises(ValueError):
        normalized_to_pixels((0.1, 0.2, 0.8, 0.9), width=0, height=100)


def test_roi_selector_resolves_builtin_runner_zone():
    profile = resolve_game_profile("subway-surfers")
    selector = ROISelector(profile)

    roi = selector.resolve("runner_lanes", width=1080, height=2400)

    assert roi.name == "runner_lanes"
    assert roi.normalized_box == (0.10, 0.58, 0.90, 0.86)
    assert roi.pixel_box == (108, 1392, 972, 2064)


def test_roi_selector_can_fallback_to_full_screen_or_raise():
    selector = ROISelector({"popup_center": (0.15, 0.2, 0.85, 0.8)})

    fallback = selector.resolve("missing", width=300, height=600)

    assert fallback.name == "full_screen"
    assert fallback.pixel_box == (0, 0, 300, 600)
    with pytest.raises(KeyError):
        selector.resolve("missing", width=300, height=600, fallback_full_screen=False)


def test_roi_selector_lists_all_zones_sorted_by_name():
    selector = ROISelector({
        "b": (0.2, 0.2, 0.8, 0.8),
        "a": (0.1, 0.1, 0.9, 0.9),
    })

    rois = selector.all(width=100, height=200)

    assert [roi.name for roi in rois] == ["a", "b"]
    assert rois[0].pixel_box == (10, 20, 90, 180)
