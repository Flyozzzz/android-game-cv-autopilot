"""JSON run report writer."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time
from typing import Any


@dataclass
class StageRecord:
    stage: str
    status: str
    elapsed_seconds: float
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class RunReport:
    """Collect a compact, secret-free run report."""

    def __init__(
        self,
        *,
        game_profile_id: str,
        game_name: str,
        game_package: str,
        enabled_stages: list[str],
        report_dir: str = "reports",
    ):
        self.started_at = datetime.now(timezone.utc)
        self.start_monotonic = time.monotonic()
        self.game_profile_id = game_profile_id
        self.game_name = game_name
        self.game_package = game_package
        self.enabled_stages = enabled_stages
        self.report_dir = Path(report_dir)
        self.records: list[StageRecord] = []
        self.path: Path | None = None

    def elapsed(self) -> float:
        return round(time.monotonic() - self.start_monotonic, 3)

    def record(
        self,
        stage: str,
        status: str,
        message: str = "",
        details: dict[str, Any] | None = None,
    ) -> None:
        self.records.append(
            StageRecord(
                stage=stage,
                status=status,
                elapsed_seconds=self.elapsed(),
                message=message,
                details=details or {},
            )
        )

    def write(self, *, final_status: str, error: str = "") -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        stamp = self.started_at.strftime("%Y%m%d_%H%M%S")
        path = self.report_dir / f"run_{stamp}.json"
        payload = {
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": self.elapsed(),
            "final_status": final_status,
            "error": error,
            "game": {
                "profile_id": self.game_profile_id,
                "name": self.game_name,
                "package": self.game_package,
            },
            "enabled_stages": self.enabled_stages,
            "stages": [asdict(record) for record in self.records],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        latest = self.report_dir / "latest_run_report.json"
        latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
        self.path = path
        return path
