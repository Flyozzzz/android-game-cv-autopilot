from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_exposes_autopilot_builder_ui_and_assets():
    html = (ROOT / "dashboard/static/index.html").read_text(encoding="utf-8")
    js = (ROOT / "dashboard/static/autopilot_builder.js").read_text(encoding="utf-8")
    css = (ROOT / "dashboard/static/autopilot_builder.css").read_text(encoding="utf-8")

    assert 'href="#autopilot-builder"' in html
    assert 'id="autopilot-builder"' in html
    assert "/static/autopilot_builder.js" in html
    assert "/static/autopilot_builder.css" in html
    for node_id in ("builderPrompt", "builderMode", "builderBuildBtn", "builderOutput", "builderBundleList"):
        assert f'id="{node_id}"' in html
    assert "/api/builder/build" in js
    assert "/api/builder/state" in js
    assert "openrouterKey" in js
    assert ".builder-layout" in css


def test_dashboard_i18n_covers_autopilot_builder():
    import json

    catalog = json.loads((ROOT / "dashboard/static/i18n.json").read_text(encoding="utf-8"))
    required = {
        "nav.builder",
        "builder.title",
        "builder.prompt",
        "builder.safety.fast",
        "builder.bundles.empty",
        "button.buildAutopilot",
        "button.refreshBuilder",
        "placeholder.builderPrompt",
    }

    assert required <= set(catalog["en"])
    assert required <= set(catalog["ru"])
    assert "local_only" in catalog["en"]["builder.safety.fast"]
    assert "local_only" in catalog["ru"]["builder.safety.fast"]
