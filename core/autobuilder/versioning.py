"""Version history and rollback support for autopilot bundles."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any

from core.autobuilder.artifact_store import ArtifactStore
from core.autobuilder.util import now_ms


class AutopilotVersionStore:
    def __init__(self, bundle_dir: str | Path):
        self.bundle_dir = Path(bundle_dir)
        self.store = ArtifactStore(self.bundle_dir)

    def add_version(self, version: str, *, change: str, test_result: dict[str, Any] | None = None) -> dict[str, Any]:
        history = self._history()
        entry = {
            "version": version,
            "change": change,
            "created_at_ms": now_ms(),
            "test_result": test_result or {},
            "rollback_files": self._snapshot_files(version),
        }
        history.append(entry)
        self.store.write_json("version_history.json", {"versions": history})
        return entry

    def rollback(self, version: str) -> dict[str, Any]:
        entry = next((item for item in self._history() if item.get("version") == version), None)
        if not entry:
            raise RuntimeError(f"unknown version: {version}")
        for rel, content in entry.get("rollback_files", {}).items():
            target = self.bundle_dir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", delete=False, dir=target.parent, encoding="utf-8") as tmp:
                tmp.write(content)
                tmp_path = Path(tmp.name)
            tmp_path.replace(target)
        return {"rolled_back": True, "version": version}

    def _history(self) -> list[dict[str, Any]]:
        path = self.bundle_dir / "version_history.json"
        if not path.exists():
            return []
        payload = json.loads(path.read_text(encoding="utf-8"))
        return list(payload.get("versions", []))

    def _snapshot_files(self, version: str) -> dict[str, str]:
        files = {}
        for name in ("autopilot.json", "profile.json", "scenario.json", "screen_graph.json", "safety_policy.json"):
            path = self.bundle_dir / name
            if path.exists():
                files[name] = path.read_text(encoding="utf-8")
        return files
