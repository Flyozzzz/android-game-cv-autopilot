"""Environment doctor for local Android automation setup."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
from typing import Callable

from core.reaction_benchmark import benchmark_capture_source


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    message: str
    hint: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def run_setup_doctor(
    *,
    runner: CommandRunner | None = None,
    env: dict[str, str] | None = None,
    python_version: tuple[int, int, int] | None = None,
    include_latency: bool = False,
) -> dict:
    runner = runner or _run
    env = env or dict(os.environ)
    version = python_version or sys.version_info[:3]
    adb_path = env.get("ADB_PATH") or shutil.which("adb") or "adb"
    checks = [
        _check_python(version),
        _check_module("PIL", "Install requirements: python3 -m pip install -r requirements.txt"),
        _check_module("cv2", "Install opencv-python-headless from requirements.txt"),
        _check_module("appium", "Install Appium-Python-Client from requirements.txt"),
        _check_adb_binary(adb_path, runner),
    ]
    devices = _adb_devices(adb_path, runner)
    checks.append(_check_devices(devices))
    checks.append(_check_docker_adb(env))
    checks.append(_check_openrouter(env))
    latency = None
    if include_latency and devices:
        latency = {}
        for source in ("adb", "adb_raw"):
            try:
                latency[source] = benchmark_capture_source(
                    source=source,
                    serial=devices[0],
                    adb_path=adb_path,
                    samples=3,
                    runner=runner,
                ).to_dict()
            except Exception as exc:
                latency[source] = {"status": "failed", "error": str(exc)}
    status = _overall_status(checks)
    return {
        "status": status,
        "platform": platform.platform(),
        "python": ".".join(str(part) for part in version),
        "adb_path": adb_path,
        "devices": devices,
        "checks": [check.to_dict() for check in checks],
        "latency": latency,
    }


def doctor_report_markdown(result: dict) -> str:
    lines = [
        f"# Android Autopilot Setup Doctor",
        "",
        f"Status: **{result.get('status', 'unknown')}**",
        f"Python: `{result.get('python', '')}`",
        f"ADB: `{result.get('adb_path', '')}`",
        "",
        "| Check | Status | Message | Hint |",
        "| --- | --- | --- | --- |",
    ]
    for check in result.get("checks", []):
        lines.append(
            f"| {check.get('name', '')} | {check.get('status', '')} | "
            f"{check.get('message', '')} | {check.get('hint', '')} |"
        )
    if result.get("latency"):
        lines += ["", "Latency:", "```json", json.dumps(result["latency"], ensure_ascii=False, indent=2), "```"]
    return "\n".join(lines)


def _check_python(version: tuple[int, int, int]) -> DoctorCheck:
    if version >= (3, 13, 0):
        return DoctorCheck("python", "ok", f"Python {version[0]}.{version[1]}.{version[2]}")
    return DoctorCheck("python", "fail", f"Python {version[0]}.{version[1]}.{version[2]} is too old", "Use Python 3.13 for this project.")


def _check_module(module: str, hint: str) -> DoctorCheck:
    if importlib.util.find_spec(module):
        return DoctorCheck(module, "ok", f"{module} import is available")
    return DoctorCheck(module, "fail", f"{module} is missing", hint)


def _check_adb_binary(adb_path: str, runner: CommandRunner) -> DoctorCheck:
    try:
        proc = runner([adb_path, "version"], 8)
    except Exception as exc:
        return DoctorCheck("adb", "fail", f"adb is not runnable: {exc}", "Install Android SDK platform-tools and set ADB_PATH if needed.")
    if proc.returncode == 0:
        return DoctorCheck("adb", "ok", "adb is runnable")
    return DoctorCheck("adb", "fail", _decode(proc.stderr) or "adb version failed", "Install Android SDK platform-tools.")


def _adb_devices(adb_path: str, runner: CommandRunner) -> list[str]:
    try:
        proc = runner([adb_path, "devices", "-l"], 8)
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    devices = []
    for line in _decode(proc.stdout).splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def _check_devices(devices: list[str]) -> DoctorCheck:
    if devices:
        return DoctorCheck("adb_device", "ok", f"{len(devices)} ADB device(s): {', '.join(devices)}")
    return DoctorCheck("adb_device", "warn", "No connected ADB device found", "Start an emulator or connect a phone with USB debugging enabled.")


def _check_docker_adb(env: dict[str, str]) -> DoctorCheck:
    socket = env.get("ADB_SERVER_SOCKET", "")
    if socket:
        return DoctorCheck("docker_adb", "ok", f"ADB_SERVER_SOCKET={socket}")
    return DoctorCheck("docker_adb", "warn", "Docker ADB bridge is not configured", "For Docker Desktop on macOS use ADB_SERVER_SOCKET=tcp:host.docker.internal:5037 and run host adb server.")


def _check_openrouter(env: dict[str, str]) -> DoctorCheck:
    if env.get("OPENROUTER_API_KEY"):
        return DoctorCheck("openrouter", "ok", "Vision key is configured")
    return DoctorCheck("openrouter", "warn", "Vision key is not configured", "Local-only/replay flows work without it; LLM fallback and Builder analysis need OPENROUTER_API_KEY.")


def _overall_status(checks: list[DoctorCheck]) -> str:
    if any(check.status == "fail" for check in checks):
        return "fail"
    if any(check.status == "warn" for check in checks):
        return "warn"
    return "ok"


def _decode(value: bytes | str) -> str:
    return value.decode(errors="ignore").strip() if isinstance(value, bytes) else str(value or "").strip()


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
