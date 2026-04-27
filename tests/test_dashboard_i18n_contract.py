import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "dashboard" / "static"


def test_dashboard_i18n_has_complete_russian_and_english_catalogs():
    catalog = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))

    assert set(catalog) == {"en", "ru"}
    en_keys = set(catalog["en"])
    ru_keys = set(catalog["ru"])
    assert en_keys == ru_keys
    assert len(en_keys) >= 90
    assert all(str(value).strip() for value in catalog["en"].values())
    assert all(str(value).strip() for value in catalog["ru"].values())


def test_dashboard_i18n_covers_constructor_cv_mcp_and_safety_copy():
    catalog = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
    required = {
        "guide.profiles.body",
        "guide.presets.body",
        "guide.cv.body",
        "guide.mcp.body",
        "guide.safety.body",
        "profiles.builder.title",
        "command.presetBuilder.title",
        "mcp.cvTools",
    }

    assert required <= set(catalog["en"])
    assert required <= set(catalog["ru"])
    assert "проф" in catalog["ru"]["guide.profiles.body"].lower()
    assert "CV" in catalog["en"]["guide.cv.body"]


def test_dashboard_html_exposes_language_controls_and_guide_section():
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="langRu"' in html
    assert 'id="langEn"' in html
    assert 'id="helpMode"' in html
    assert 'id="guide"' in html
    assert 'data-i18n="guide.profiles.body"' in html
    assert html.count("data-i18n=") >= 70


def test_dashboard_js_loads_and_applies_i18n():
    js = (STATIC / "app.js").read_text(encoding="utf-8")

    assert "loadTranslations" in js
    assert "applyTranslations" in js
    assert "localStorage.setItem(\"dashboard.language\"" in js
    assert "document.documentElement.lang" in js
    assert "data-i18n-placeholder" in js
