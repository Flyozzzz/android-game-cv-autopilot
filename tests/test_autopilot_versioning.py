from core.autobuilder.versioning import AutopilotVersionStore


def test_autopilot_versioning_records_history_and_rolls_back(tmp_path):
    (tmp_path / "profile.json").write_text('{"version":1}', encoding="utf-8")
    store = AutopilotVersionStore(tmp_path)

    entry = store.add_version("0.1.0", change="initial")
    (tmp_path / "profile.json").write_text('{"version":2}', encoding="utf-8")
    rolled = store.rollback(entry["version"])

    assert rolled["rolled_back"] is True
    assert '"version":1' in (tmp_path / "profile.json").read_text(encoding="utf-8")
