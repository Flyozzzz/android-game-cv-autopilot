"""Human approval queue for risky autopilot patches."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from core.autobuilder.artifact_store import ArtifactStore
from core.autobuilder.patches import AutopilotPatch
from core.autobuilder.util import now_ms


class PatchReviewQueue:
    def __init__(self, root: str | Path):
        self.store = ArtifactStore(root)

    def submit(self, patch: AutopilotPatch, *, ttl_ms: int = 86_400_000) -> dict[str, Any]:
        review_id = f"review_{now_ms()}"
        payload = {
            "id": review_id,
            "patch": patch.to_dict(),
            "status": "pending",
            "created_at_ms": now_ms(),
            "expires_at_ms": now_ms() + ttl_ms,
            "audit": [{"event": "submitted", "at_ms": now_ms()}],
        }
        self.store.write_json(f"patches/{review_id}.json", payload)
        return payload

    def decide(self, review_id: str, *, approve: bool, actor: str = "user") -> dict[str, Any]:
        payload = self.store.read_json(f"patches/{review_id}.json")
        if payload["status"] != "pending":
            raise RuntimeError(f"review is not pending: {payload['status']}")
        if now_ms() > int(payload.get("expires_at_ms", 0)):
            payload["status"] = "expired"
        else:
            payload["status"] = "approved" if approve else "rejected"
        payload.setdefault("audit", []).append({"event": payload["status"], "actor": actor, "at_ms": now_ms()})
        self.store.write_json(f"patches/{review_id}.json", payload)
        return payload
