import subprocess
from io import BytesIO

from PIL import Image

from core.autobuilder.live_exploration import default_live_exploration_actions, run_live_exploration


def _png(color: str) -> bytes:
    image = Image.new("RGB", (64, 96), color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_live_exploration_records_four_real_actions_and_transitions(tmp_path):
    screenshots = [_png(color) for color in ("black", "red", "green", "blue", "white")]
    calls: list[list[str]] = []

    def runner(args, timeout):
        calls.append(args)
        joined = " ".join(args)
        if "screencap -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=screenshots.pop(0), stderr=b"")
        if "uiautomator dump" in joined:
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<hierarchy rotation="0">'
                '<node text="Settings" content-desc="" resource-id="android:id/title" bounds="[0,0][10,10]" />'
                "</hierarchy>\nUI hierarchy dumped to: /dev/tty"
            )
            return subprocess.CompletedProcess(args, 0, stdout=xml.encode(), stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    result = run_live_exploration(
        serial="device-1",
        adb_path="adb",
        actions=default_live_exploration_actions(),
        output_dir=tmp_path,
        runner=runner,
        settle_seconds=0,
    )

    report = result.to_report()
    assert report["status"] == "ok"
    assert report["metrics"]["actions"] == 4
    assert report["metrics"]["frames"] == 5
    assert report["metrics"]["transitions"] == 4
    assert len(list(tmp_path.glob("frame_*.png"))) == 5
    assert [step.action["type"] for step in result.state.steps] == ["swipe", "swipe", "swipe", "swipe"]
    assert sum(1 for call in calls if "input" in call) == 4
