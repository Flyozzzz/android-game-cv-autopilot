"""Lightweight latency metrics and trace event collection."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4


LATENCY_FIELDS = (
    "capture_ms",
    "decode_ms",
    "resize_ms",
    "provider_uiautomator_ms",
    "provider_template_ms",
    "provider_ocr_ms",
    "provider_detector_ms",
    "provider_llm_ms",
    "fusion_ms",
    "action_ms",
    "loop_total_ms",
    "fps",
)


@dataclass(frozen=True)
class TraceEvent:
    """A single perception/action decision trace."""

    run_id: str
    profile_id: str = ""
    screen_id: str = ""
    frame_source: str = ""
    goal: str = ""
    roi: dict[str, Any] | None = None
    providers_called: list[str] = field(default_factory=list)
    candidates: list[dict[str, Any]] = field(default_factory=list)
    selected_candidate: dict[str, Any] | None = None
    action: dict[str, Any] | None = None
    policy_result: str = ""
    latency_breakdown: dict[str, float] = field(default_factory=dict)
    llm_called: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MetricsCollector:
    """In-memory rolling metrics for local runs and tests."""

    def __init__(self, *, max_events: int = 200):
        self.max_events = max(1, int(max_events or 1))
        self.latencies: dict[str, list[float]] = {name: [] for name in LATENCY_FIELDS}
        self.trace_events: list[TraceEvent] = []
        self.counters: dict[str, int] = {}

    def reset(self) -> None:
        for values in self.latencies.values():
            values.clear()
        self.trace_events.clear()
        self.counters.clear()

    def increment(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + int(amount)

    def record_latency(self, name: str, elapsed_ms: float) -> None:
        if name not in self.latencies:
            self.latencies[name] = []
        values = self.latencies[name]
        values.append(round(float(elapsed_ms), 3))
        del values[:-self.max_events]

    @contextmanager
    def timer(self, name: str) -> Iterator[None]:
        started = perf_counter()
        try:
            yield
        finally:
            self.record_latency(name, (perf_counter() - started) * 1000.0)

    def record_trace(self, event: TraceEvent) -> None:
        self.trace_events.append(event)
        del self.trace_events[:-self.max_events]
        if event.llm_called:
            self.increment("llm_called")

    def snapshot(self) -> dict[str, Any]:
        latency_summary: dict[str, dict[str, float | int]] = {}
        for name, values in self.latencies.items():
            if not values:
                continue
            latency_summary[name] = {
                "count": len(values),
                "last_ms": values[-1],
                "avg_ms": round(sum(values) / len(values), 3),
                "max_ms": max(values),
            }
        return {
            "latencies": latency_summary,
            "counters": dict(self.counters),
            "latest_trace": self.trace_events[-1].to_dict() if self.trace_events else None,
        }


GLOBAL_METRICS = MetricsCollector()


def new_run_id() -> str:
    return uuid4().hex


def record_latency(name: str, elapsed_ms: float) -> None:
    GLOBAL_METRICS.record_latency(name, elapsed_ms)


def record_trace(event: TraceEvent) -> None:
    GLOBAL_METRICS.record_trace(event)


def metrics_snapshot() -> dict[str, Any]:
    return GLOBAL_METRICS.snapshot()


def reset_metrics() -> None:
    GLOBAL_METRICS.reset()
