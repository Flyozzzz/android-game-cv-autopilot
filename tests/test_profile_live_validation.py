import struct
import subprocess
from io import BytesIO

from PIL import Image
import pytest

from core.game_profiles import resolve_game_profile
from core.profile_live_validation import (
    promoted_profile_payload,
    validate_profile_live,
    validate_profiles_live,
    write_promoted_profile,
)


def _png() -> bytes:
    image = Image.new("RGB", (8, 8), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


RAW = struct.pack("<IIII", 1, 1, 1, 1) + bytes([1, 2, 3, 255])
XML = b'UI hierchary dumped to: /dev/tty\n<hierarchy><node text="Play" content-desc="" resource-id="btn"/></hierarchy>'


def _runner(installed: bool = True):
    def run(args, timeout):
        joined = " ".join(args)
        if "pm path" in joined:
            return subprocess.CompletedProcess(args, 0 if installed else 1, stdout=b"package:/base.apk" if installed else b"", stderr=b"")
        if "dumpsys package" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"versionName=1.2\nversionCode=3", stderr=b"")
        if "monkey -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"Events injected", stderr=b"")
        if "dumpsys window windows" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"mCurrentFocus=Window{u0 com.example/.Main}", stderr=b"")
        if "screencap -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=_png(), stderr=b"")
        if joined.endswith("exec-out screencap"):
            return subprocess.CompletedProcess(args, 0, stdout=RAW, stderr=b"")
        if "uiautomator dump" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=XML, stderr=b"")
        if "input swipe" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"bad command")

    return run


def test_validate_profile_live_records_launch_capture_and_safe_exploration(tmp_path):
    profile = resolve_game_profile("subway-surfers")

    report = validate_profile_live(
        profile,
        serial="emu",
        output_root=tmp_path,
        runner=_runner(installed=True),
    ).to_dict()

    assert report["status"] == "passed"
    assert report["validation_status"] == "validated"
    assert report["installed"] is True
    assert report["launch_ok"] is True
    assert report["latency"]["adb"]["name"] == "adb_screencap"
    assert report["latency"]["adb_raw"]["name"] == "adb_raw_screencap"
    assert report["exploration"]["metrics"]["actions"] == 4
    assert "safe_exploration" in report["validation_scope"]


def test_validate_profile_live_keeps_missing_package_unpromoted(tmp_path):
    profile = resolve_game_profile("clash-royale")

    report = validate_profile_live(
        profile,
        serial="emu",
        output_root=tmp_path,
        runner=_runner(installed=False),
    ).to_dict()

    assert report["status"] == "failed"
    assert report["validation_status"] == "starter"
    assert any("not_installed" in item for item in report["failures"])
    with pytest.raises(RuntimeError):
        promoted_profile_payload(profile, report)


def test_validate_profiles_live_writes_report_and_promoted_profile(tmp_path):
    summary = validate_profiles_live(
        serial="emu",
        profile_ids=["subway-surfers"],
        output_root=tmp_path / "reports",
        runner=_runner(installed=True),
        explore=False,
    )
    profile = resolve_game_profile("subway-surfers")
    path = write_promoted_profile(
        profile,
        summary["profiles"][0],
        output_dir=tmp_path / "profiles",
        status="validated",
    )

    assert summary["passed"] == 1
    assert (tmp_path / "reports").exists()
    assert path.exists()
    assert '"validation_status": "validated"' in path.read_text(encoding="utf-8")
