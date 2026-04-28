"""Template configuration registry for image-based element detection."""
from __future__ import annotations

from dataclasses import dataclass, field
import glob
import json
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class TemplateSpec:
    id: str
    paths: tuple[str, ...]
    threshold: float = 0.82
    scales: tuple[float, ...] = (1.0,)
    roi: str = ""
    tap_offset: tuple[float, float] = (0.5, 0.5)
    negative_templates: tuple[str, ...] = ()
    search_step: int = 1

    @classmethod
    def from_mapping(cls, data: dict[str, Any]) -> "TemplateSpec":
        template_id = str(data.get("id") or "").strip()
        if not template_id:
            raise ValueError("Template spec requires id")
        paths = tuple(str(path) for path in data.get("paths") or () if str(path).strip())
        if not paths:
            raise ValueError(f"Template spec {template_id!r} requires paths")
        scales = tuple(float(scale) for scale in data.get("scales") or (1.0,))
        tap_offset_raw = data.get("tap_offset") or data.get("tapOffset") or (0.5, 0.5)
        if len(tap_offset_raw) != 2:
            tap_offset_raw = (0.5, 0.5)
        tap_offset = (
            max(0.0, min(1.0, float(tap_offset_raw[0]))),
            max(0.0, min(1.0, float(tap_offset_raw[1]))),
        )
        return cls(
            id=template_id,
            paths=paths,
            threshold=max(0.0, min(1.0, float(data.get("threshold", 0.82)))),
            scales=scales or (1.0,),
            roi=str(data.get("roi") or "").strip(),
            tap_offset=tap_offset,
            negative_templates=tuple(
                str(item).strip()
                for item in data.get("negative_templates") or data.get("negativeTemplates") or ()
                if str(item).strip()
            ),
            search_step=max(1, int(data.get("search_step") or data.get("searchStep") or 1)),
        )


@dataclass
class TemplateRegistry:
    specs: dict[str, TemplateSpec] = field(default_factory=dict)

    @classmethod
    def from_file(cls, path: str | Path) -> "TemplateRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(payload, dict) and "templates" in payload:
            payload = payload["templates"]
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list):
            raise ValueError("Template registry file must contain a template object or list")
        return cls.from_mappings(payload)

    @classmethod
    def from_mappings(cls, items: list[dict[str, Any]]) -> "TemplateRegistry":
        registry = cls()
        for item in items:
            registry.add(TemplateSpec.from_mapping(item))
        return registry

    def add(self, spec: TemplateSpec) -> None:
        self.specs[spec.id] = spec

    def get(self, template_id: str) -> TemplateSpec | None:
        return self.specs.get(template_id)

    def all(self) -> list[TemplateSpec]:
        return list(self.specs.values())

    def expanded_paths(self, spec: TemplateSpec) -> list[Path]:
        paths: list[Path] = []
        for pattern in spec.paths:
            matches = [Path(path) for path in glob.glob(pattern)]
            if matches:
                paths.extend(matches)
            else:
                paths.append(Path(pattern))
        return [path for path in paths if path.exists()]
