"""Profile maturity and readiness checks.

The project should not present starter hints as universal, proven autopilots.
This module centralizes the status labels used by CLI, dashboard, MCP, docs,
and tests.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


MATURE_STATUSES = {"proven", "validated"}
STARTER_STATUSES = {"starter", "helper", "blocked", "unknown"}


@dataclass(frozen=True)
class ProfileReadinessIssue:
    code: str
    severity: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def normalize_validation_status(value: str = "", *, proven: bool = False, notes: str = "") -> str:
    raw = str(value or "").strip().lower().replace("_", "-")
    if proven:
        return "proven"
    if raw in MATURE_STATUSES | STARTER_STATUSES:
        return raw
    lowered_notes = str(notes or "").lower()
    if any(word in lowered_notes for word in ("blocker", "blocked", "login/server", "server blocker")):
        return "blocked"
    return "starter"


def profile_maturity(profile: Any) -> str:
    return normalize_validation_status(
        getattr(profile, "validation_status", ""),
        proven=bool(getattr(profile, "proven", False)),
        notes=str(getattr(profile, "notes", "")),
    )


def profile_is_production_ready(profile: Any) -> bool:
    return profile_maturity(profile) in MATURE_STATUSES and _scope_covers_strategy(profile)


def profile_readiness_issues(profile: Any) -> list[ProfileReadinessIssue]:
    issues: list[ProfileReadinessIssue] = []
    maturity = profile_maturity(profile)
    package = str(getattr(profile, "package", "") or "").strip()
    zones = dict(getattr(profile, "screen_zones", {}) or {})
    strategy = str(getattr(profile, "gameplay_strategy", "none") or "none")

    if not package:
        issues.append(ProfileReadinessIssue("missing_package", "fail", "Profile has no Android package name."))
    if not zones:
        issues.append(ProfileReadinessIssue("missing_roi", "fail", "Profile has no normalized screen_zones/ROI."))
    if maturity not in MATURE_STATUSES:
        issues.append(ProfileReadinessIssue("not_proven", "warn", f"Profile maturity is {maturity}; run replay and live validation before treating it as proven."))
    elif not _scope_covers_strategy(profile):
        issues.append(ProfileReadinessIssue("scope_not_validated", "warn", "Profile has validation evidence, but not for its gameplay strategy scope."))
    if strategy == "fast_runner" and "runner_lanes" not in zones:
        issues.append(ProfileReadinessIssue("missing_runner_lanes", "fail", "Fast runner profiles require runner_lanes ROI."))
    if strategy == "match3_solver" and "match3_board" not in zones:
        issues.append(ProfileReadinessIssue("missing_match3_board", "fail", "Match-3 profiles require match3_board ROI."))
    return issues


def profile_validation_summary(profile: Any) -> dict[str, Any]:
    issues = profile_readiness_issues(profile)
    maturity = profile_maturity(profile)
    return {
        "maturity": maturity,
        "production_ready": profile_is_production_ready(profile) and not any(issue.severity == "fail" for issue in issues),
        "readiness_issues": [issue.to_dict() for issue in issues],
        "validation_scope": list(getattr(profile, "validation_scope", ()) or ()),
        "last_validated": str(getattr(profile, "last_validated", "") or ""),
        "validation_runs": int(getattr(profile, "validation_runs", 0) or 0),
    }


def profile_validation_matrix(profiles: list[Any] | tuple[Any, ...]) -> list[dict[str, Any]]:
    return [
        {
            "id": getattr(profile, "id", ""),
            "name": getattr(profile, "name", ""),
            "package": getattr(profile, "package", ""),
            "strategy": getattr(profile, "gameplay_strategy", "none"),
            **profile_validation_summary(profile),
        }
        for profile in profiles
    ]


def _scope_covers_strategy(profile: Any) -> bool:
    strategy = str(getattr(profile, "gameplay_strategy", "none") or "none")
    scope = {str(item).strip().lower() for item in (getattr(profile, "validation_scope", ()) or ())}
    if strategy == "fast_runner":
        return bool(scope & {"fast_gameplay", "fast_runner_live", "runner_live"})
    if strategy == "match3_solver":
        return bool(scope & {"match3_live", "match3_solver", "solver_unit"})
    return bool(scope & {"launch", "tutorial", "purchase_preview", "safe_exploration", "install"})
