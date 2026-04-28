from core.autobuilder.eval_suite import evaluate_autopilot


def test_eval_suite_reports_quality_metrics():
    report = evaluate_autopilot([
        {"status": "passed", "loop_total_ms": 20, "llm_calls": 0, "forbidden_actions_count": 0, "template_hit_rate": 1.0},
        {"status": "failed", "loop_total_ms": 40, "llm_calls": 2, "forbidden_actions_count": 1, "template_hit_rate": 0.5},
    ])

    assert report["success_rate"] == 0.5
    assert report["avg_loop_ms"] == 30
    assert report["llm_calls_per_run"] == 1
    assert report["forbidden_actions_count"] == 1
