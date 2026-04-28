import json

import pytest

from core.autobuilder.artifact_store import ArtifactStore
from core.autobuilder.schemas import SchemaValidationError


def test_artifact_store_writes_atomically_validates_and_redacts(tmp_path):
    store = ArtifactStore(tmp_path)
    path = store.write_json(
        "goal.json",
        {
            "app_name": "Game",
            "goal": "open",
            "mode": "create",
            "allowed_actions": ["launch"],
            "forbidden_actions": [],
            "runtime_strategy": "generic_app",
            "budgets": {},
            "requires_human_review": True,
            "api_key": "secret",
        },
        schema="goal_spec",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["api_key"] == "[REDACTED]"
    assert store.read_json("goal.json", schema="goal_spec")["app_name"] == "Game"


def test_artifact_store_rejects_invalid_schema_without_replacing(tmp_path):
    store = ArtifactStore(tmp_path)
    with pytest.raises(SchemaValidationError):
        store.write_json("bad.json", {"app_name": "x"}, schema="goal_spec")
    assert not (tmp_path / "bad.json").exists()
