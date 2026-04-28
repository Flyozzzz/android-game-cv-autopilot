from io import BytesIO

from PIL import Image, ImageDraw

from core.autobuilder.builder import AutopilotBuilder, BuildOptions


def _frame_file(tmp_path):
    image = Image.new("RGB", (80, 80), "white")
    ImageDraw.Draw(image).rectangle((20, 20, 39, 39), fill="green")
    buf = BytesIO()
    image.save(buf, format="PNG")
    path = tmp_path / "screen.png"
    path.write_bytes(buf.getvalue())
    return path


def test_autopilot_builder_creates_bundle_with_replay_template_eval_and_version(tmp_path):
    async def llm(_prompt, _screenshot):
        return {
            "screen_type": "main_menu",
            "summary": "Main menu with Play button",
            "safe_elements": [
                {"name": "play_button", "description": "Play", "roi": "bottom_buttons", "recommended_action": "tap", "bbox": [20, 20, 40, 40], "confidence": 0.95}
            ],
            "risky_elements": [{"name": "shop_button", "reason": "purchase"}],
            "next_best_goal": "tap_play_button",
        }

    result = AutopilotBuilder().build(
        "Create autopilot for Subway Surfers. No purchases, no login, no multiplayer.",
        BuildOptions(output_root=tmp_path / "autopilots", frame_paths=[_frame_file(tmp_path)], llm=llm, launch_app=False),
    )

    bundle_dir = tmp_path / "autopilots" / "subway-surfers"
    assert result["status"] == "ok"
    assert (bundle_dir / "autopilot.json").exists()
    assert (bundle_dir / "profile.json").exists()
    assert (bundle_dir / "screen_graph.json").exists()
    assert (bundle_dir / "version_history.json").exists()
    assert result["replay_report"]["status"] == "passed"
    assert result["template_mining"]["verified"] == ["play-button"]
    assert result["profile"]["runtime"]["fast_gameplay"] == "local_only"
