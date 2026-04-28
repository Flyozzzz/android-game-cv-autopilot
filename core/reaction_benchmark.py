"""Reaction-speed benchmarks for local Android automation paths."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import statistics
import subprocess
from time import perf_counter
from typing import Callable


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


@dataclass(frozen=True)
class BenchmarkResult:
    name: str
    samples: int
    avg_ms: float
    p95_ms: float
    max_ms: float
    target_ms: float
    status: str
    recommendation: str

    def to_dict(self) -> dict:
        return asdict(self)


def classify_capture_latency(avg_ms: float) -> tuple[str, str]:
    if avg_ms <= 80:
        return "fast", "Suitable for local-first menu loops and light realtime helpers."
    if avg_ms <= 180:
        return "usable", "Usable for menus/tutorials; prefer streaming for action gameplay."
    return "slow", "ADB screencap is too slow for fast gameplay; use replay/scrcpy/minicap and local-only runtime."


def benchmark_adb_screencap(
    *,
    serial: str = "",
    adb_path: str = "adb",
    samples: int = 3,
    runner: CommandRunner | None = None,
) -> BenchmarkResult:
    runner = runner or _run
    timings: list[float] = []
    for _ in range(max(1, int(samples or 1))):
        cmd = [adb_path]
        if serial:
            cmd += ["-s", serial]
        cmd += ["exec-out", "screencap", "-p"]
        started = perf_counter()
        proc = runner(cmd, 20)
        elapsed = (perf_counter() - started) * 1000.0
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "adb screencap benchmark failed")
        stdout = proc.stdout if isinstance(proc.stdout, bytes) else str(proc.stdout).encode()
        if not stdout.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("adb screencap benchmark did not return PNG")
        timings.append(elapsed)
    avg = statistics.fmean(timings)
    p95 = _percentile(timings, 0.95)
    status, recommendation = classify_capture_latency(avg)
    return BenchmarkResult(
        name="adb_screencap",
        samples=len(timings),
        avg_ms=round(avg, 3),
        p95_ms=round(p95, 3),
        max_ms=round(max(timings), 3),
        target_ms=80.0,
        status=status,
        recommendation=recommendation,
    )


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def _decode(value: bytes | str) -> str:
    return value.decode(errors="ignore").strip() if isinstance(value, bytes) else str(value or "").strip()


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
