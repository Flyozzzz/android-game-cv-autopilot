from core.autobuilder.roi_generator import generate_roi_zones


def test_roi_generator_merges_defaults_and_analysis_boxes():
    zones = generate_roi_zones(
        strategy="runner",
        screen_width=1000,
        screen_height=2000,
        analysis={"safe_elements": [{"name": "play button", "bbox": [100, 1500, 900, 1900]}]},
    )

    assert zones["runner_lanes"] == [0.1, 0.58, 0.9, 0.86]
    assert zones["play-button"] == [0.1, 0.75, 0.9, 0.95]
