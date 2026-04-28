"""Live validation runner for generated autopilots on ADB devices."""
from __future__ import annotations

from typing import Any

from core.autobuilder.app_manager import AppManager
from core.autobuilder.safety_policy import SafetyPolicy


def run_live_validation(
    bundle: dict[str, Any],
    *,
    serial: str = "",
    adb_path: str = "adb",
    runner=None,
    policy: SafetyPolicy | None = None,
) -> dict[str, Any]:
    profile = bundle.get("profile", {})
    package = str(profile.get("package") or "")
    failures: list[str] = []
    actions: list[dict[str, Any]] = []
    if not package:
        failures.append("profile package is missing")
        return _report(failures, actions)
    manager = AppManager(serial=serial, adb_path=adb_path, runner=runner, policy=policy or SafetyPolicy())
    info = manager.get_package_info(package)
    if not info.installed:
        failures.append(f"app is not installed: {package}")
        return _report(failures, actions)
    launched = manager.launch_app(package)
    actions.append({"type": "launch_app", "package": package, "activity": launched.current_activity})
    scenario = bundle.get("scenario", {})
    if any(step.get("type") == "enter_fast_gameplay" for step in scenario.get("steps", [])):
        if profile.get("runtime", {}).get("fast_gameplay") != "local_only":
            failures.append("fast gameplay would call non-local runtime")
    return _report(failures, actions)


def _report(failures: list[str], actions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "actions": actions,
        "metrics": {
            "actions": len(actions),
            "failures": len(failures),
            "fast_gameplay_llm_calls": 0,
        },
    }
