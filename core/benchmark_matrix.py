"""Benchmark matrix for evidence-backed profile/device validation."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import subprocess
from typing import Any, Callable

from core.autobuilder.domain import AppTarget, DeviceTarget, ValidationOutcome
from core.game_profiles import GameProfile, list_game_profiles
from core.profile_live_validation import validate_profile_live


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def run_benchmark_matrix(
    *,
    serial: str,
    profile_ids: list[str] | tuple[str, ...] | None = None,
    runs: int = 20,
    adb_path: str = "adb",
    output_root: str | Path = "reports/benchmark_matrix",
    runner: CommandRunner | None = None,
    explore: bool = True,
) -> dict[str, Any]:
    if not serial:
        raise RuntimeError("benchmark matrix requires an ADB serial")
    runner = runner or _run
    run_count = max(1, int(runs or 1))
    device = read_device_target(serial=serial, adb_path=adb_path, runner=runner)
    profiles = _select_profiles(profile_ids)
    generated_at = datetime.now(timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    output = Path(output_root)
    output.mkdir(parents=True, exist_ok=True)

    for profile in profiles:
        outcomes: list[dict[str, Any]] = []
        for index in range(1, run_count + 1):
            report = validate_profile_live(
                profile,
                serial=serial,
                adb_path=adb_path,
                output_root=output / profile.id / f"run_{index:02d}",
                runner=runner,
                explore=explore,
            ).to_dict()
            outcomes.append(_outcome_from_report(report, index).to_dict())
        successes = sum(1 for item in outcomes if item["ok"])
        first_failure = next((item for item in outcomes if not item["ok"]), None)
        app = AppTarget(
            profile_id=profile.id,
            name=profile.name,
            package=profile.package,
            strategy=profile.gameplay_strategy,
        )
        rows.append(
            {
                "device": device.to_dict(),
                "app": app.to_dict(),
                "profile_id": profile.id,
                "profile_status": profile.validation_status,
                "runs": run_count,
                "successes": successes,
                "failures": run_count - successes,
                "success_rate": round(successes / run_count, 4),
                "result": "passed" if successes == run_count else "failed",
                "break_stage": "" if first_failure is None else first_failure["stage"],
                "break_reason": "" if first_failure is None else first_failure["reason"],
                "outcomes": outcomes,
            }
        )

    matrix = {
        "generated_at": generated_at,
        "device": device.to_dict(),
        "runs_per_profile": run_count,
        "rows": rows,
        "summary": {
            "profiles": len(rows),
            "passed_profiles": sum(1 for row in rows if row["result"] == "passed"),
            "failed_profiles": sum(1 for row in rows if row["result"] != "passed"),
        },
    }
    path = output / f"benchmark_matrix_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2), encoding="utf-8")
    matrix["report_path"] = str(path)
    return matrix


def read_device_target(*, serial: str, adb_path: str = "adb", runner: CommandRunner | None = None) -> DeviceTarget:
    runner = runner or _run
    return DeviceTarget(
        serial=serial,
        model=_adb_prop(serial, adb_path, runner, "ro.product.model"),
        android_version=_adb_prop(serial, adb_path, runner, "ro.build.version.release"),
        sdk=_adb_prop(serial, adb_path, runner, "ro.build.version.sdk"),
        resolution=_adb_wm_size(serial, adb_path, runner),
    )


def _outcome_from_report(report: dict[str, Any], index: int) -> ValidationOutcome:
    failures = [str(item) for item in report.get("failures") or []]
    status = "passed" if report.get("status") == "passed" else "failed"
    stage = "complete" if status == "passed" else _failure_stage(failures)
    reason = "" if status == "passed" else "; ".join(failures) or "unknown failure"
    metrics = {
        "run_index": index,
        "latency": report.get("latency") or {},
        "exploration_metrics": (report.get("exploration") or {}).get("metrics") or {},
    }
    return ValidationOutcome(status=status, stage=stage, reason=reason, metrics=metrics)


def _failure_stage(failures: list[str]) -> str:
    joined = " ".join(failures).lower()
    if "not_installed" in joined:
        return "install"
    if "launch_failed" in joined or "resolve" in joined:
        return "launch"
    if "capture" in joined or "screencap" in joined:
        return "capture"
    if "exploration" in joined or "swipe" in joined:
        return "exploration"
    return "unknown"


def _select_profiles(profile_ids: list[str] | tuple[str, ...] | None) -> list[GameProfile]:
    profiles = list(list_game_profiles())
    if not profile_ids:
        return profiles
    wanted = {str(item).strip() for item in profile_ids if str(item).strip()}
    return [profile for profile in profiles if profile.id in wanted or profile.package in wanted]


def _adb_prop(serial: str, adb_path: str, runner: CommandRunner, prop: str) -> str:
    proc = runner([adb_path, "-s", serial, "shell", "getprop", prop], 8)
    return _decode(proc.stdout).strip() if proc.returncode == 0 else ""


def _adb_wm_size(serial: str, adb_path: str, runner: CommandRunner) -> str:
    proc = runner([adb_path, "-s", serial, "shell", "wm", "size"], 8)
    if proc.returncode != 0:
        return ""
    output = _decode(proc.stdout)
    if ":" in output:
        return output.split(":", 1)[1].strip()
    return output.strip()


def _decode(data: bytes | str) -> str:
    return data.decode(errors="ignore").strip() if isinstance(data, bytes) else str(data or "").strip()


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
