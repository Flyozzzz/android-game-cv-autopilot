from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_manual_recorder_uses_real_timing_and_drag_swipes():
    app_js = (ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")

    assert "pause: 0.45" not in app_js
    assert "previous.pause" in app_js
    assert "pointerdown" in app_js
    assert "pointerup" in app_js
    assert "/api/device/swipe" in app_js
    assert 'id="swipeLeftBtn"' in index_html
    assert 'id="swipeRightBtn"' in index_html


def test_dashboard_exposes_cv_test_bench():
    app_js = (ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")
    index_html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
    styles_css = (ROOT / "dashboard/static/styles.css").read_text(encoding="utf-8")

    for node_id in ("cvTestGoal", "cvPlanBtn", "cvRunGoalBtn", "cvTestOutput"):
        assert f'id="{node_id}"' in index_html
    assert 'href="#cv-bench"' in index_html
    assert 'id="cv-bench"' in index_html
    assert 'data-i18n="cvtest.title"' in index_html
    assert "span-12" in index_html
    assert ".span-12" in styles_css
    assert "grid-column: 1 / -1" in styles_css
    assert '"/api/cv/plan"' in app_js
    assert '"/api/cv/run"' in app_js
    assert "cvTestOutput" in app_js


def test_dashboard_masks_device_serials_in_visible_ui():
    app_js = (ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")

    assert "function deviceDisplayName" in app_js
    assert "option.value = device.serial" in app_js
    assert "option.textContent = deviceDisplayName(device, index)" in app_js
    assert "card.querySelector(\"strong\").textContent = deviceDisplayName(device, index)" in app_js
    assert "strong>${device.serial}" not in app_js
