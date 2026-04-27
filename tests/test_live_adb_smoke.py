import os
import shutil
import subprocess

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.live_adb]


def _adb_path() -> str:
    return os.getenv("ADB_PATH") or shutil.which("adb") or "adb"


def _connected_devices() -> list[str]:
    proc = subprocess.run(
        [_adb_path(), "devices", "-l"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
    )
    if proc.returncode != 0:
        return []
    serials = []
    for line in proc.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials


def _target_serial() -> str:
    devices = _connected_devices()
    if not devices:
        pytest.skip("No live ADB device connected")
    requested = (os.getenv("LOCAL_DEVICE") or "").strip()
    if requested and requested.lower() not in {"auto", "first"}:
        if requested not in devices:
            pytest.skip(f"LOCAL_DEVICE={requested} not connected; connected={devices}")
        return requested
    return devices[0]


def test_live_adb_screenshot_and_ui_dump_are_available():
    """Read-only smoke test for a real phone or emulator connected over ADB."""

    serial = _target_serial()
    shot = subprocess.run(
        [_adb_path(), "-s", serial, "exec-out", "screencap", "-p"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20,
    )
    assert shot.returncode == 0, shot.stderr.decode(errors="ignore")
    assert shot.stdout.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(shot.stdout) > 1000

    ui = subprocess.run(
        [_adb_path(), "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=25,
    )
    assert ui.returncode == 0, ui.stderr
    assert "<hierarchy" in ui.stdout
    assert "package=" in ui.stdout
