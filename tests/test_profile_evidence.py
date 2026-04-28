import json
from pathlib import Path

from core.profile_evidence import load_profile_evidence, profile_evidence_summary
from core.profile_validation import profile_readiness_issues, profile_validation_summary


def test_checked_in_profile_evidence_covers_five_validated_profiles(tmp_path):
    expected_profiles = {
        "android-settings": ("launch", "capture"),
        "brawl-stars": ("launch", "capture", "safe_exploration"),
        "candy-crush": ("launch", "capture", "safe_exploration"),
        "subway-surfers": ("launch", "capture", "safe_exploration"),
        "talking-tom": ("launch", "capture", "safe_exploration"),
    }

    for profile_id, expected_scope in expected_profiles.items():
        summary = profile_evidence_summary(profile_id, report_root=tmp_path / "missing_reports")
        latest = summary["latest"]

        assert summary["count"] == 1
        assert latest["result"] == "passed"
        assert tuple(latest["scope"]) == expected_scope
        assert latest["source"].startswith(f"profiles/{profile_id}/evidence/")
        assert Path(latest["live_report"]).exists()
        assert latest["frames"]
        assert all(Path(frame).exists() for frame in latest["frames"])


def test_profile_evidence_loads_plugin_records(tmp_path):
    evidence_dir = tmp_path / "profiles" / "talking-tom" / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "live_20260428.json").write_text(
        json.dumps({
            "profile_id": "talking-tom",
            "result": "passed",
            "maturity": "proven",
            "scope": ["launch", "capture", "safe_exploration"],
            "validated_at": "2026-04-28",
            "device": {"serial": "device-1", "resolution": "1080x2400"},
            "app": {"package": "com.example.tom", "version": "1.2.3"},
            "runtime": {"frame_source": "scrcpy_raw", "model": "xiaomi/mimo-v2.5"},
            "artifacts": {
                "live_report": "reports/profile_validation/profile_live_validation_2026-04-28.json",
                "frames": ["reports/profile_validation/talking-tom/frames/frame_000.png"],
            },
            "limits": ["Validated only on device-1."],
        }),
        encoding="utf-8",
    )

    evidence = load_profile_evidence("talking-tom", evidence_root=tmp_path / "profiles", report_root=tmp_path / "reports")
    summary = profile_evidence_summary("talking-tom", evidence_root=tmp_path / "profiles", report_root=tmp_path / "reports")

    assert len(evidence) == 1
    assert evidence[0].maturity == "proven"
    assert evidence[0].device["serial"] == "device-1"
    assert summary["count"] == 1
    assert summary["latest_result"] == "passed"
    assert summary["latest_scope"] == ["launch", "capture", "safe_exploration"]


def test_profile_evidence_loads_legacy_live_reports(tmp_path):
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "profile_live_validation_2026-04-28.json").write_text(
        json.dumps({
            "profiles": [{
                "profile_id": "candy-crush",
                "package": "com.king.candycrushsaga",
                "status": "passed",
                "validation_status": "validated",
                "validation_scope": ["launch", "capture", "safe_exploration"],
                "serial": "device-2",
                "current_activity": ".Main",
                "validated_on": "2026-04-28",
                "latency": {"adb": {"status": "slow"}},
                "exploration": {
                    "status": "ok",
                    "frames": ["reports/profile_validation/candy-crush/frames/frame_000.png"],
                },
            }]
        }),
        encoding="utf-8",
    )

    evidence = load_profile_evidence("candy-crush", evidence_root=tmp_path / "profiles", report_root=report_dir)

    assert len(evidence) == 1
    assert evidence[0].live_report.endswith("profile_live_validation_2026-04-28.json")
    assert evidence[0].app["package"] == "com.king.candycrushsaga"
    assert evidence[0].runtime["frame_sources"] == ["adb"]


def test_profile_evidence_prefers_tracked_plugin_record_over_legacy_report(tmp_path):
    evidence_dir = tmp_path / "profiles" / "talking-tom" / "evidence"
    evidence_dir.mkdir(parents=True)
    (evidence_dir / "live_20260428.json").write_text(
        json.dumps({
            "profile_id": "talking-tom",
            "result": "passed",
            "maturity": "proven",
            "scope": ["launch"],
            "validated_at": "2026-04-28",
            "artifacts": {
                "live_report": "profiles/talking-tom/validation/live_20260428/live_report.json",
                "frames": ["profiles/talking-tom/validation/live_20260428/frames/frame_000.png"],
            },
        }),
        encoding="utf-8",
    )
    report_dir = tmp_path / "reports"
    report_dir.mkdir()
    (report_dir / "profile_live_validation_2026-04-28.json").write_text(
        json.dumps({
            "profiles": [{
                "profile_id": "talking-tom",
                "status": "passed",
                "validation_status": "validated",
                "validation_scope": ["launch"],
                "validated_on": "2026-04-28",
                "exploration": {"frames": ["reports/profile_validation/talking-tom/frame_000.png"]},
            }]
        }),
        encoding="utf-8",
    )

    summary = profile_evidence_summary("talking-tom", evidence_root=tmp_path / "profiles", report_root=report_dir)

    assert summary["count"] == 2
    assert summary["latest"]["source"].endswith("profiles/talking-tom/evidence/live_20260428.json")
    assert summary["latest"]["live_report"].startswith("profiles/talking-tom/validation")


def test_profile_validation_summary_includes_evidence_and_warns_without_it(monkeypatch, tmp_path):
    class Profile:
        id = "custom"
        package = "com.example.custom"
        screen_zones = {"main": (0.1, 0.1, 0.9, 0.9)}
        validation_status = "validated"
        proven = False
        notes = ""
        gameplay_strategy = "none"
        validation_scope = ("launch",)
        last_validated = "2026-04-28"
        validation_runs = 1

    monkeypatch.setenv("PROFILE_EVIDENCE_DIR", str(tmp_path / "profiles"))
    monkeypatch.setenv("PROFILE_LIVE_REPORT_DIR", str(tmp_path / "reports"))

    summary = profile_validation_summary(Profile())
    issues = profile_readiness_issues(Profile(), evidence=summary["evidence"])

    assert summary["evidence"]["count"] == 0
    assert any(issue.code == "missing_evidence" for issue in issues)
