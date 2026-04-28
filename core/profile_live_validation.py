"""Evidence-backed live validation for built-in/custom game profiles."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
import json
import subprocess
from typing import Any, Callable

from core.autobuilder.app_manager import AppManager
from core.autobuilder.live_exploration import default_live_exploration_actions, run_live_exploration
from core.autobuilder.safety_policy import SafetyPolicy
from core.game_profiles import GameProfile, list_game_profiles
from core.profile_validation import profile_maturity
from core.reaction_benchmark import benchmark_capture_source


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


@dataclass(frozen=True)
class ProfileLiveValidation:
    profile_id: str
    name: str
    package: str
    status: str
    validation_status: str
    validation_scope: tuple[str, ...]
    serial: str
    installed: bool
    launch_ok: bool
    current_activity: str
    latency: dict[str, Any]
    exploration: dict[str, Any]
    failures: tuple[str, ...]
    validated_on: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["validation_scope"] = list(self.validation_scope)
        data["failures"] = list(self.failures)
        return data


def validate_profile_live(
    profile: GameProfile,
    *,
    serial: str,
    adb_path: str = "adb",
    output_root: str | Path = "reports/profile_validation",
    runner: CommandRunner | None = None,
    explore: bool = True,
) -> ProfileLiveValidation:
    runner = runner or _run
    failures: list[str] = []
    policy = SafetyPolicy()
    manager = AppManager(serial=serial, adb_path=adb_path, runner=runner, policy=policy, test_device=True)
    info = manager.get_package_info(profile.package)
    launch_ok = False
    current_activity = ""
    if not info.installed:
        failures.append(f"not_installed:{profile.package}")
    else:
        try:
            launched = manager.launch_app(profile.package)
            launch_ok = True
            current_activity = launched.current_activity
        except Exception as exc:
            failures.append(f"launch_failed:{exc}")

    latency: dict[str, Any] = {}
    if launch_ok:
        for source in ("adb", "adb_raw"):
            try:
                latency[source] = benchmark_capture_source(
                    source=source,
                    serial=serial,
                    adb_path=adb_path,
                    samples=2,
                    runner=runner,
                ).to_dict()
            except Exception as exc:
                latency[source] = {"status": "failed", "error": str(exc)}

    exploration: dict[str, Any] = {"status": "skipped", "actions": [], "failures": [], "metrics": {}}
    if launch_ok and explore:
        try:
            output_dir = Path(output_root) / profile.id / "frames"
            result = run_live_exploration(
                serial=serial,
                adb_path=adb_path,
                actions=default_live_exploration_actions(),
                output_dir=output_dir,
                policy=policy,
                runner=runner,
            )
            exploration = result.to_report()
            if exploration.get("status") != "ok":
                failures.extend(str(item) for item in exploration.get("failures", []))
        except Exception as exc:
            failures.append(f"exploration_failed:{exc}")
            exploration = {"status": "failed", "actions": [], "failures": [str(exc)], "metrics": {}}

    status = "passed" if not failures and launch_ok else "failed"
    scope = ["launch", "capture"]
    if explore:
        scope.append("safe_exploration")
    validation_status = "validated" if status == "passed" else profile_maturity(profile)
    return ProfileLiveValidation(
        profile_id=profile.id,
        name=profile.name,
        package=profile.package,
        status=status,
        validation_status=validation_status,
        validation_scope=tuple(scope),
        serial=serial,
        installed=bool(info.installed),
        launch_ok=launch_ok,
        current_activity=current_activity,
        latency=latency,
        exploration=exploration,
        failures=tuple(failures),
        validated_on=date.today().isoformat(),
    )


def validate_profiles_live(
    *,
    serial: str,
    profile_ids: list[str] | tuple[str, ...] | None = None,
    adb_path: str = "adb",
    output_root: str | Path = "reports/profile_validation",
    runner: CommandRunner | None = None,
    explore: bool = True,
) -> dict[str, Any]:
    selected = _select_profiles(profile_ids)
    reports = [
        validate_profile_live(
            profile,
            serial=serial,
            adb_path=adb_path,
            output_root=output_root,
            runner=runner,
            explore=explore,
        ).to_dict()
        for profile in selected
    ]
    summary = {
        "serial": serial,
        "validated_on": date.today().isoformat(),
        "profiles": reports,
        "passed": sum(1 for item in reports if item["status"] == "passed"),
        "failed": sum(1 for item in reports if item["status"] != "passed"),
    }
    Path(output_root).mkdir(parents=True, exist_ok=True)
    report_path = Path(output_root) / f"profile_live_validation_{date.today().isoformat()}.json"
    report_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    summary["report_path"] = str(report_path)
    return summary


def promoted_profile_payload(profile: GameProfile, report: dict[str, Any], *, status: str = "validated") -> dict[str, Any]:
    if report.get("status") != "passed":
        raise RuntimeError(f"profile {profile.id} cannot be promoted without passed validation")
    status = "proven" if status == "proven" or profile.proven else "validated"
    scope = _dedupe([*list(profile.validation_scope or ()), *list(report.get("validation_scope") or ())])
    return {
        "id": profile.id,
        "name": profile.name,
        "package": profile.package,
        "aliases": list(profile.aliases),
        "player_name_prefix": profile.player_name_prefix,
        "install_query": profile.install_query,
        "tutorial_hints": list(profile.tutorial_hints),
        "purchase_hints": list(profile.purchase_hints),
        "blocker_words": list(profile.blocker_words),
        "gameplay_strategy": profile.gameplay_strategy,
        "proven": status == "proven",
        "validation_status": status,
        "validation_scope": scope,
        "validation_runs": int(profile.validation_runs or 0) + 1,
        "last_validated": str(report.get("validated_on") or date.today().isoformat()),
        "notes": f"Live validation passed on {report.get('serial', '')}: {', '.join(report.get('validation_scope') or [])}.",
        "max_tutorial_steps": profile.max_tutorial_steps,
        "max_purchase_steps": profile.max_purchase_steps,
        "screen_zones": {key: list(value) for key, value in profile.screen_zones.items()},
    }


def write_promoted_profile(
    profile: GameProfile,
    report: dict[str, Any],
    *,
    output_dir: str | Path = "dashboard/profiles",
    status: str = "validated",
) -> Path:
    payload = promoted_profile_payload(profile, report, status=status)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    path = output / f"{profile.id}.json"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def _select_profiles(profile_ids: list[str] | tuple[str, ...] | None) -> list[GameProfile]:
    profiles = list(list_game_profiles())
    if not profile_ids:
        return profiles
    wanted = {str(item).strip() for item in profile_ids if str(item).strip()}
    return [profile for profile in profiles if profile.id in wanted or profile.package in wanted]


def _dedupe(values: list[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
