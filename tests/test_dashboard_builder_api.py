from io import BytesIO

from PIL import Image

from dashboard.api_builder import build_autopilot_from_payload, builder_state


def test_dashboard_builder_api_builds_bundle_from_payload_without_device(tmp_path, monkeypatch):
    import dashboard.api_builder as api_builder

    monkeypatch.setattr(api_builder, "ROOT", tmp_path)
    image = Image.new("RGB", (32, 32), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    frame = tmp_path / "frame.png"
    frame.write_bytes(buf.getvalue())

    result = build_autopilot_from_payload({
        "prompt": "Create autopilot for Custom App. Open main screen.",
        "framePaths": [str(frame)],
        "launchApp": False,
    })

    assert result["goal_spec"]["app_name"] == "Custom App"
    assert (tmp_path / "autopilots" / "custom-app" / "autopilot.json").exists()
    assert builder_state()["bundles"][0]["id"] == "custom-app"


def test_dashboard_builder_api_requires_prompt():
    try:
        build_autopilot_from_payload({"prompt": ""})
    except RuntimeError as exc:
        assert "prompt is required" in str(exc)
    else:
        raise AssertionError("empty prompt must fail")
