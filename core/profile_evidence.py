"""Evidence records for profile maturity claims."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_EVIDENCE_DIR = ROOT / "profiles"
DEFAULT_LIVE_REPORT_DIR = ROOT / "reports" / "profile_validation"
EVIDENCE_STATUSES = {"passed", "failed", "skipped"}
MATURITY_LABELS = {
    "proven",
    "validated",
    "beta",
    "experimental",
    "template-only",
    "deprecated",
}


@dataclass(frozen=True)
class ProfileEvidence:
    profile_id: str
    result: str
    maturity: str
    scope: tuple[str, ...]
    validated_at: str
    source: str
    live_report: str = ""
    replay_report: str = ""
    frames: tuple[str, ...] = ()
    logs: tuple[str, ...] = ()
    device: dict[str, Any] = field(default_factory=dict)
    app: dict[str, Any] = field(default_factory=dict)
    runtime: dict[str, Any] = field(default_factory=dict)
    limits: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope"] = list(self.scope)
        data["frames"] = list(self.frames)
        data["logs"] = list(self.logs)
        data["limits"] = list(self.limits)
        return data


def profile_evidence_dir() -> Path:
    return Path(os.getenv("PROFILE_EVIDENCE_DIR", str(DEFAULT_EVIDENCE_DIR)))


def live_report_dir() -> Path:
    return Path(os.getenv("PROFILE_LIVE_REPORT_DIR", str(DEFAULT_LIVE_REPORT_DIR)))


def load_profile_evidence(
    profile_or_id: Any,
    *,
    evidence_root: str | Path | None = None,
    report_root: str | Path | None = None,
) -> tuple[ProfileEvidence, ...]:
    profile_id = _profile_id(profile_or_id)
    if not profile_id:
        return ()
    evidence: list[ProfileEvidence] = []
    evidence.extend(_load_plugin_evidence(profile_id, Path(evidence_root) if evidence_root else profile_evidence_dir()))
    evidence.extend(_load_live_report_evidence(profile_id, Path(report_root) if report_root else live_report_dir()))
    evidence.sort(key=lambda item: (item.validated_at, _source_priority(item.source), item.source), reverse=True)
    return tuple(evidence)


def profile_evidence_summary(
    profile_or_id: Any,
    *,
    evidence_root: str | Path | None = None,
    report_root: str | Path | None = None,
) -> dict[str, Any]:
    evidence = load_profile_evidence(profile_or_id, evidence_root=evidence_root, report_root=report_root)
    latest = evidence[0] if evidence else None
    return {
        "count": len(evidence),
        "has_passed_live": any(item.result == "passed" and item.live_report for item in evidence),
        "latest": latest.to_dict() if latest else {},
        "latest_result": latest.result if latest else "",
        "latest_validated_at": latest.validated_at if latest else "",
        "latest_scope": list(latest.scope) if latest else [],
        "latest_device": dict(latest.device) if latest else {},
        "latest_app": dict(latest.app) if latest else {},
        "sources": [item.source for item in evidence],
    }


def _load_plugin_evidence(profile_id: str, root: Path) -> list[ProfileEvidence]:
    paths = sorted((root / profile_id / "evidence").glob("*.json")) if root.exists() else []
    evidence: list[ProfileEvidence] = []
    for path in paths:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        item = _evidence_from_mapping(raw, source=_display_path(path))
        if item and item.profile_id == profile_id:
            evidence.append(item)
    return evidence


def _load_live_report_evidence(profile_id: str, root: Path) -> list[ProfileEvidence]:
    if not root.exists():
        return []
    evidence: list[ProfileEvidence] = []
    for report_path in sorted(root.glob("profile_live_validation_*.json")):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for raw_profile in report.get("profiles") or []:
            if str(raw_profile.get("profile_id") or "") != profile_id:
                continue
            evidence.append(_evidence_from_live_report(raw_profile, report_path))
    return evidence


def _evidence_from_mapping(raw: dict[str, Any], *, source: str) -> ProfileEvidence | None:
    profile_id = str(raw.get("profile_id") or raw.get("profileId") or "").strip()
    if not profile_id:
        return None
    result = _choice(raw.get("result") or raw.get("status"), EVIDENCE_STATUSES, "skipped")
    maturity = _choice(raw.get("maturity"), MATURITY_LABELS, "experimental")
    artifacts = raw.get("artifacts") if isinstance(raw.get("artifacts"), dict) else {}
    return ProfileEvidence(
        profile_id=profile_id,
        result=result,
        maturity=maturity,
        scope=_tuple(raw.get("scope") or raw.get("validation_scope")),
        validated_at=str(raw.get("validated_at") or raw.get("validatedOn") or raw.get("validated_on") or "").strip(),
        source=source,
        live_report=str(artifacts.get("live_report") or raw.get("live_report") or "").strip(),
        replay_report=str(artifacts.get("replay_report") or raw.get("replay_report") or "").strip(),
        frames=_tuple(artifacts.get("frames") or raw.get("frames")),
        logs=_tuple(artifacts.get("logs") or raw.get("logs")),
        device=dict(raw.get("device") or {}),
        app=dict(raw.get("app") or {}),
        runtime=dict(raw.get("runtime") or {}),
        limits=_tuple(raw.get("limits")),
    )


def _evidence_from_live_report(raw_profile: dict[str, Any], report_path: Path) -> ProfileEvidence:
    exploration = raw_profile.get("exploration") if isinstance(raw_profile.get("exploration"), dict) else {}
    return ProfileEvidence(
        profile_id=str(raw_profile.get("profile_id") or ""),
        result=_choice(raw_profile.get("status"), EVIDENCE_STATUSES, "skipped"),
        maturity=_choice(raw_profile.get("validation_status"), MATURITY_LABELS, "validated"),
        scope=_tuple(raw_profile.get("validation_scope")),
        validated_at=str(raw_profile.get("validated_on") or ""),
        source=_display_path(report_path),
        live_report=_display_path(report_path),
        frames=_tuple(exploration.get("frames")),
        device={
            "serial": raw_profile.get("serial") or "",
        },
        app={
            "package": raw_profile.get("package") or "",
            "activity": raw_profile.get("current_activity") or "",
        },
        runtime={
            "frame_sources": sorted((raw_profile.get("latency") or {}).keys()),
            "exploration_status": exploration.get("status") or "",
        },
        limits=(
            "Evidence scope is limited to the recorded device, app version, language, and resolution.",
            "Live report validates only the listed scope, not universal gameplay automation.",
        ),
    )


def _profile_id(profile_or_id: Any) -> str:
    if isinstance(profile_or_id, str):
        return profile_or_id.strip()
    return str(getattr(profile_or_id, "id", "") or "").strip()


def _choice(value: Any, allowed: set[str], default: str) -> str:
    normalized = str(value or "").strip().lower().replace("_", "-")
    return normalized if normalized in allowed else default


def _tuple(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    return (str(value).strip(),) if str(value).strip() else ()


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


def _source_priority(source: str) -> int:
    normalized = str(source or "").replace("\\", "/")
    return 1 if normalized.startswith("profiles/") or "/profiles/" in normalized else 0
