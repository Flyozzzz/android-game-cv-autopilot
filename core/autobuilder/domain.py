"""Small domain model shared by autobuilder runtime and validation tools."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class DeviceTarget:
    serial: str
    model: str = ""
    android_version: str = ""
    sdk: str = ""
    resolution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AppTarget:
    profile_id: str
    name: str
    package: str
    strategy: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValidationOutcome:
    status: str
    stage: str
    reason: str = ""
    metrics: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        return self.status == "passed"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ok"] = self.ok
        data["metrics"] = dict(self.metrics or {})
        return data
