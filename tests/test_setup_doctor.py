import struct
import subprocess

import asyncio

from core.frame_source import Frame
from core.reaction_benchmark import (
    benchmark_adb_raw_screencap,
    benchmark_adb_screencap,
    benchmark_scrcpy_raw_stream,
    classify_capture_latency,
    classify_stream_latency,
)
from core.setup_doctor import doctor_report_markdown, run_setup_doctor


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 128
RAW = struct.pack("<IIII", 1, 1, 1, 1) + bytes([1, 2, 3, 255])


def test_reaction_benchmark_classifies_adb_capture_latency():
    calls = []

    def runner(args, timeout):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=PNG, stderr=b"")

    result = benchmark_adb_screencap(serial="emu", adb_path="adb-test", samples=2, runner=runner)

    assert result.name == "adb_screencap"
    assert result.samples == 2
    assert result.status in {"fast", "usable", "slow"}
    assert all(call[:3] == ["adb-test", "-s", "emu"] for call in calls)
    assert classify_capture_latency(220)[0] == "slow"

    raw_result = benchmark_adb_raw_screencap(serial="emu", adb_path="adb-test", samples=2, runner=lambda args, timeout: subprocess.CompletedProcess(args, 0, stdout=RAW, stderr=b""))
    assert raw_result.name == "adb_raw_screencap"


def test_reaction_benchmark_supports_scrcpy_raw_stream_with_fake_source():
    class FakeSource:
        def __init__(self):
            self.ts = 100

        async def latest_frame(self):
            self.ts += 1
            return Frame(self.ts, 2, 2, b"\x00" * 12, None, "scrcpy_raw", 1.0)

        def close(self):
            return None

    result = asyncio.run(benchmark_scrcpy_raw_stream(samples=2, source_factory=FakeSource))

    assert result.name == "scrcpy_raw_stream"
    assert result.samples == 2
    assert result.status in {"fast", "usable", "slow"}
    assert classify_stream_latency(120)[0] == "slow"


def test_setup_doctor_reports_actionable_environment_state():
    def runner(args, timeout):
        joined = " ".join(args)
        if joined == "adb-test version":
            return subprocess.CompletedProcess(args, 0, stdout=b"Android Debug Bridge version 1.0", stderr=b"")
        if joined == "adb-test devices -l":
            return subprocess.CompletedProcess(args, 0, stdout=b"List of devices attached\nemu device model:Pixel\n", stderr=b"")
        if "screencap -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=PNG, stderr=b"")
        if "exec-out screencap" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=RAW, stderr=b"")
        return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"bad")

    result = run_setup_doctor(
        runner=runner,
        env={"ADB_PATH": "adb-test", "ADB_SERVER_SOCKET": "tcp:host.docker.internal:5037"},
        python_version=(3, 13, 0),
        include_latency=True,
    )
    report = doctor_report_markdown(result)

    assert result["status"] in {"ok", "warn"}
    assert result["devices"] == ["emu"]
    assert result["latency"]["adb"]["name"] == "adb_screencap"
    assert result["latency"]["adb_raw"]["name"] == "adb_raw_screencap"
    assert "Setup Doctor" in report


def test_setup_doctor_checks_streaming_binaries_when_selected(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/bin/ls" if name in {"ffmpeg", "scrcpy"} else None)

    result = run_setup_doctor(
        runner=lambda args, timeout: subprocess.CompletedProcess(args, 0, stdout=b"Android Debug Bridge version 1.0", stderr=b""),
        env={"ADB_PATH": "adb-test", "FRAME_SOURCE": "scrcpy_raw"},
        python_version=(3, 13, 0),
    )

    checks = {check["name"]: check["status"] for check in result["checks"]}
    assert checks["ffmpeg"] == "ok"
    assert checks["scrcpy"] == "ok"


def test_setup_doctor_accepts_scrcpy_server_path_without_scrcpy_binary(monkeypatch, tmp_path):
    server = tmp_path / "scrcpy-server"
    server.write_text("server", encoding="utf-8")
    monkeypatch.setattr("shutil.which", lambda name: "/bin/ls" if name == "ffmpeg" else None)

    result = run_setup_doctor(
        runner=lambda args, timeout: subprocess.CompletedProcess(args, 0, stdout=b"Android Debug Bridge version 1.0", stderr=b""),
        env={"ADB_PATH": "adb-test", "FRAME_SOURCE": "scrcpy_raw", "SCRCPY_SERVER_PATH": str(server)},
        python_version=(3, 13, 0),
    )

    checks = {check["name"]: check["status"] for check in result["checks"]}
    assert checks["ffmpeg"] == "ok"
    assert checks["scrcpy_server"] == "ok"
    assert "scrcpy" not in checks
