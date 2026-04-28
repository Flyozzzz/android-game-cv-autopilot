import subprocess

from core.reaction_benchmark import benchmark_adb_screencap, classify_capture_latency
from core.setup_doctor import doctor_report_markdown, run_setup_doctor


PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 128


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


def test_setup_doctor_reports_actionable_environment_state():
    def runner(args, timeout):
        joined = " ".join(args)
        if joined == "adb-test version":
            return subprocess.CompletedProcess(args, 0, stdout=b"Android Debug Bridge version 1.0", stderr=b"")
        if joined == "adb-test devices -l":
            return subprocess.CompletedProcess(args, 0, stdout=b"List of devices attached\nemu device model:Pixel\n", stderr=b"")
        if "screencap -p" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=PNG, stderr=b"")
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
    assert result["latency"]["name"] == "adb_screencap"
    assert "Setup Doctor" in report
