"""Evaluation metrics for generated autopilot bundles."""
from __future__ import annotations

from typing import Any

from core.autobuilder.schemas import validate_schema


def evaluate_autopilot(reports: list[dict[str, Any]]) -> dict[str, Any]:
    effective_reports = [report for report in reports if report.get("status") not in {"skipped", "skip"}]
    total = len(effective_reports)
    successes = sum(1 for report in effective_reports if report.get("status") in {"passed", "ok", "success"})
    loop_times = [
        float((report.get("avg_loop_ms") if report.get("avg_loop_ms") is not None else report.get("loop_total_ms")) or 0)
        for report in effective_reports
        if report.get("avg_loop_ms") is not None or report.get("loop_total_ms") is not None
    ]
    llm_calls = [float(report.get("llm_calls", 0) or 0) for report in effective_reports]
    forbidden = sum(int(report.get("forbidden_actions_count", 0) or 0) for report in effective_reports)
    eval_report = {
        "success_rate": round(successes / total, 4) if total else 0.0,
        "avg_loop_ms": round(sum(loop_times) / len(loop_times), 3) if loop_times else 0.0,
        "llm_calls_per_run": round(sum(llm_calls) / total, 3) if total else 0.0,
        "forbidden_actions_count": forbidden,
        "template_hit_rate": _avg(effective_reports, "template_hit_rate"),
        "cache_hit_rate": _avg(effective_reports, "cache_hit_rate"),
        "unknown_screen_count": sum(int(report.get("unknown_screen_count", 0) or 0) for report in effective_reports),
        "repair_success_rate": _avg(effective_reports, "repair_success_rate"),
        "action_failure_rate": _avg(effective_reports, "action_failure_rate"),
    }
    validate_schema("eval_report", eval_report)
    return eval_report


def _avg(reports: list[dict[str, Any]], key: str) -> float:
    values = [float(report.get(key, 0) or 0) for report in reports]
    return round(sum(values) / len(values), 4) if values else 0.0
