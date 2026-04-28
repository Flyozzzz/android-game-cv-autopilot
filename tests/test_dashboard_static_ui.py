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
    assert 'openrouterKey: getInput("openrouterKey")' in app_js
    assert 'models: getInput("cvModels")' in app_js
    assert "cvTestOutput" in app_js


def test_dashboard_exposes_read_only_vision_inspector():
    index_html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
    inspector_js = (ROOT / "dashboard/static/vision_inspector.js").read_text(encoding="utf-8")
    overlay_css = (ROOT / "dashboard/static/vision_overlay.css").read_text(encoding="utf-8")

    assert 'href="#vision-inspector"' in index_html
    assert 'id="vision-inspector"' in index_html
    assert 'data-i18n="nav.inspector"' in index_html
    assert 'data-i18n="vision.title"' in index_html
    assert 'data-i18n="vision.how.title"' in index_html
    assert 'data-i18n="vision.how.step4"' in index_html
    assert 'data-i18n="vision.legend.selected.desc"' in index_html
    assert 'data-i18n="vision.legend.drawn.desc"' in index_html
    assert "/static/vision_inspector.js" in index_html
    assert "/static/vision_overlay.css" in index_html
    assert "/api/vision/inspector" in inspector_js
    assert "visionInspectorOverlay" in inspector_js
    assert "vision.status.ready" in inspector_js
    assert "common.yes" in inspector_js
    assert "attachDrawing" in inspector_js
    assert "latestDrawnBox" in inspector_js
    assert "renderSaveResult" in inspector_js
    assert "openSavedProfile" in inspector_js
    assert "latestEditableProfilePath" in inspector_js
    assert "loadTemplates" in inspector_js
    assert "renderTemplateList" in inspector_js
    assert "screenshotBase64()" in inspector_js
    assert "vision.error.roiNameRequired" in inspector_js
    assert ".vision-overlay" in overlay_css
    assert ".vision-box.selected" in overlay_css
    assert ".vision-drawn" in overlay_css
    assert ".vision-help" in overlay_css
    assert ".vision-saved" in overlay_css
    assert ".vision-template-library" in overlay_css
    assert ".vision-template-item" in overlay_css
    assert ".legend-swatch.selected" in overlay_css
    assert ".legend-swatch.drawn" in overlay_css


def test_dashboard_exposes_vision_inspector_editing_controls():
    index_html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
    inspector_js = (ROOT / "dashboard/static/vision_inspector.js").read_text(encoding="utf-8")

    for node_id in (
        "visionTemplateId",
        "visionTemplateNamespace",
        "visionTemplateThreshold",
        "visionSaveTemplateBtn",
        "visionRoiName",
        "visionCreateRoiBtn",
        "visionClearDrawnBoxBtn",
        "visionExportLabelBtn",
        "visionOpenSavedProfileBtn",
        "visionSaveResult",
        "visionRefreshTemplatesBtn",
        "visionTemplateList",
    ):
        assert f'id="{node_id}"' in index_html
    assert 'data-i18n="button.saveTemplate"' in index_html
    assert 'data-i18n="vision.templateThreshold"' in index_html
    assert 'data-i18n="button.createRoiFromSelected"' in index_html
    assert 'data-i18n="button.clearDrawnBox"' in index_html
    assert 'data-i18n="button.openProfileJson"' in index_html
    assert 'data-i18n="button.refreshTemplates"' in index_html
    assert 'data-i18n="vision.editorHint"' in index_html
    assert 'data-i18n="vision.saved.title"' in index_html
    assert 'data-i18n="vision.templates.title"' in index_html
    assert 'data-i18n-placeholder="placeholder.roiZone"' in index_html
    assert "/api/vision/templates" in inspector_js
    assert "/api/vision/roi" in inspector_js
    assert "/api/vision/labels" in inspector_js


def test_dashboard_guide_and_mcp_include_builder_and_inspector():
    index_html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")

    assert "vision_inspector_state" in index_html
    assert "list_vision_templates" in index_html
    assert "save_vision_template" in index_html
    assert "create_vision_roi" in index_html
    assert "export_vision_label" in index_html
    assert "autopilot_builder_state" in index_html
    assert "build_autopilot" in index_html
    assert 'data-i18n="guide.inspector.title"' in index_html
    assert 'data-i18n="guide.builder.title"' in index_html


def test_dashboard_masks_device_serials_in_visible_ui():
    app_js = (ROOT / "dashboard/static/app.js").read_text(encoding="utf-8")

    assert "function deviceDisplayName" in app_js
    assert "option.value = device.serial" in app_js
    assert "option.textContent = deviceDisplayName(device, index)" in app_js
    assert "card.querySelector(\"strong\").textContent = deviceDisplayName(device, index)" in app_js
    assert "strong>${device.serial}" not in app_js
