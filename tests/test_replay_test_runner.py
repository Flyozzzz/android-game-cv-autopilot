import asyncio
from io import BytesIO

from PIL import Image

from core.autobuilder.replay_test_runner import run_replay_tests


def test_replay_test_runner_checks_bundle_without_phone(tmp_path):
    image = Image.new("RGB", (24, 24), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    frame = tmp_path / "frame.png"
    frame.write_bytes(buf.getvalue())
    bundle = {
        "profile": {"runtime": {"fast_gameplay": "local_only"}, "screen_zones": {"main_canvas": [0, 0, 1, 1]}},
        "scenario": {"steps": [{"type": "launch_app"}, {"type": "enter_fast_gameplay"}]},
    }

    report = asyncio.run(run_replay_tests(bundle, frame_paths=[frame], templates_root=tmp_path / "templates"))

    assert report["status"] == "passed"
    assert report["metrics"]["frames"] == 1
    assert report["failures"] == []
