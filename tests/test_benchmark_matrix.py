import struct
import subprocess
from io import BytesIO

from PIL import Image

from core.autobuilder.domain import AppTarget, DeviceTarget, ValidationOutcome
from core.benchmark_matrix import read_device_target, run_benchmark_matrix


def _png() -> bytes:
    image = Image.new("RGB", (6, 6), "white")
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()


RAW = struct.pack("<IIII", 1, 1, 1, 1) + bytes([1, 2, 3, 255])
XML = b"<hierarchy><node text=\"Play\" /></hierarchy>"


def _runner(installed=True):
    def run(args, timeout):
        joined = " ".join(args)
        if "getprop ro.product.model" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"Pixel Test\n", stderr=b"")
        if "getprop ro.build.version.release" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"15\n", stderr=b"")
        if "getprop ro.build.version.sdk" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"35\n", stderr=b"")
        if "wm size" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"Physical size: 1080x2400\n", stderr=b"")
        if "pm path" in joined:
            return subprocess.CompletedProcess(args, 0 if installed else 1, stdout=b"package:/base.apk" if installed else b"", stderr=b"")
        if "dumpsys package" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"versionName=1\nversionCode=1", stderr=b"")
        if "cmd package resolve-activity --brief" in joined:
            package = args[-1]
            return subprocess.CompletedProcess(args, 0, stdout=f"{package}/.Main\n".encode(), stderr=b"")
        if "am start -n" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"Starting", stderr=b"")
        if "dumpsys window windows" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"mCurrentFocus=Window{u0 pkg/.Main}", stderr=b"")
        if "screencap -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=_png(), stderr=b"")
        if joined.endswith("exec-out screencap"):
            return subprocess.CompletedProcess(args, 0, stdout=RAW, stderr=b"")
        if "uiautomator dump" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=XML, stderr=b"")
        if "input swipe" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    return run


def test_domain_models_are_explicit_serializable_contracts():
    assert DeviceTarget("emu", model="Pixel").to_dict()["model"] == "Pixel"
    assert AppTarget("p", "Game", "pkg").to_dict()["package"] == "pkg"
    outcome = ValidationOutcome("passed", "complete")
    assert outcome.ok is True
    assert outcome.to_dict()["ok"] is True


def test_benchmark_matrix_records_device_profile_successes_and_report(tmp_path):
    matrix = run_benchmark_matrix(
        serial="emu",
        profile_ids=["subway-surfers"],
        runs=2,
        output_root=tmp_path,
        runner=_runner(installed=True),
        explore=True,
    )

    row = matrix["rows"][0]
    assert matrix["device"]["model"] == "Pixel Test"
    assert row["profile_id"] == "subway-surfers"
    assert row["runs"] == 2
    assert row["successes"] == 2
    assert row["result"] == "passed"
    assert row["break_stage"] == ""
    assert len(row["outcomes"]) == 2
    assert (tmp_path / matrix["report_path"].split("/")[-1]).exists()


def test_benchmark_matrix_marks_install_breakage(tmp_path):
    matrix = run_benchmark_matrix(
        serial="emu",
        profile_ids=["clash-royale"],
        runs=1,
        output_root=tmp_path,
        runner=_runner(installed=False),
        explore=False,
    )

    row = matrix["rows"][0]
    assert row["result"] == "failed"
    assert row["break_stage"] == "install"
    assert row["successes"] == 0


def test_read_device_target_reads_android_identity():
    device = read_device_target(serial="emu", runner=_runner())

    assert device.android_version == "15"
    assert device.sdk == "35"
    assert device.resolution == "1080x2400"
