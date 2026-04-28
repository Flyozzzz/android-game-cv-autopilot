"""Atomic validated artifact writes for generated autopilot files."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from core.autobuilder.redaction import redact_obj
from core.autobuilder.schemas import validate_schema


class ArtifactStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative_path: str | Path, payload: dict[str, Any], *, schema: str | None = None) -> Path:
        if schema:
            validate_schema(schema, payload)
        safe_payload = redact_obj(payload)
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", delete=False, dir=target.parent, encoding="utf-8") as tmp:
            json.dump(safe_payload, tmp, ensure_ascii=False, indent=2)
            tmp.write("\n")
            tmp_path = Path(tmp.name)
        if schema:
            validate_schema(schema, json.loads(tmp_path.read_text(encoding="utf-8")))
        tmp_path.replace(target)
        return target

    def read_json(self, relative_path: str | Path, *, schema: str | None = None) -> dict[str, Any]:
        payload = json.loads((self.root / relative_path).read_text(encoding="utf-8"))
        if schema:
            validate_schema(schema, payload)
        return payload
