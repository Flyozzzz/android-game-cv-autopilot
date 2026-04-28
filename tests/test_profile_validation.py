from core.game_profiles import resolve_game_profile
from core.profile_validation import (
    normalize_validation_status,
    profile_is_production_ready,
    profile_readiness_issues,
    profile_validation_matrix,
)


def test_profile_maturity_separates_proven_validated_and_scope_gaps():
    tom = resolve_game_profile("talking-tom")
    subway = resolve_game_profile("subway-surfers")
    brawl = resolve_game_profile("brawl-stars")

    assert profile_is_production_ready(tom) is True
    assert profile_is_production_ready(subway) is False
    assert profile_is_production_ready(brawl) is True
    assert normalize_validation_status("", notes="server blocker") == "blocked"


def test_profile_readiness_reports_strategy_scope_requirements():
    profile = resolve_game_profile("subway-surfers")

    issues = profile_readiness_issues(profile)

    assert any(issue.code == "scope_not_validated" for issue in issues)
    assert not any(issue.code == "missing_runner_lanes" for issue in issues)


def test_profile_validation_matrix_is_dashboard_ready():
    matrix = profile_validation_matrix([resolve_game_profile("tom"), resolve_game_profile("candy")])

    assert matrix[0]["maturity"] == "proven"
    assert matrix[0]["production_ready"] is True
    assert matrix[1]["maturity"] == "validated"
    assert matrix[1]["production_ready"] is True
