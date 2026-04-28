"""Reaction-speed benchmarks for local Android automation paths."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
import statistics
import subprocess
import threading
import time
from time import perf_counter
from typing import Callable

from core.frame_source import ScrcpyRawStreamFrameSource, raw_screencap_to_rgb


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


def classify_stream_latency(avg_ms: float) -> tuple[str, str]:
    if avg_ms <= 45:
        return "fast", "Suitable for realtime local-only gameplay perception."
    if avg_ms <= 90:
        return "usable", "Usable for local-only fast helpers; keep providers cheap and ROI-limited."
    return "slow", "Stream is not fast enough for action gameplay on this device/settings."


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


def benchmark_adb_raw_screencap(
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
        cmd += ["exec-out", "screencap"]
        started = perf_counter()
        proc = runner(cmd, 20)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "adb raw screencap benchmark failed")
        stdout = proc.stdout if isinstance(proc.stdout, bytes) else str(proc.stdout).encode()
        raw_screencap_to_rgb(stdout)
        elapsed = (perf_counter() - started) * 1000.0
        timings.append(elapsed)
    avg = statistics.fmean(timings)
    p95 = _percentile(timings, 0.95)
    status, recommendation = classify_capture_latency(avg)
    return BenchmarkResult(
        name="adb_raw_screencap",
        samples=len(timings),
        avg_ms=round(avg, 3),
        p95_ms=round(p95, 3),
        max_ms=round(max(timings), 3),
        target_ms=80.0,
        status=status,
        recommendation=recommendation,
    )


def benchmark_capture_source(
    *,
    source: str = "adb",
    serial: str = "",
    adb_path: str = "adb",
    samples: int = 3,
    runner: CommandRunner | None = None,
    nudge_key: int | None = None,
) -> BenchmarkResult:
    source = str(source or "adb").strip().lower()
    if source == "adb":
        return benchmark_adb_screencap(serial=serial, adb_path=adb_path, samples=samples, runner=runner)
    if source == "adb_raw":
        return benchmark_adb_raw_screencap(serial=serial, adb_path=adb_path, samples=samples, runner=runner)
    if source == "scrcpy_raw":
        return asyncio.run(
            benchmark_scrcpy_raw_stream(
                serial=serial,
                adb_path=adb_path,
                samples=samples,
                nudge_key=nudge_key,
            )
        )
    raise ValueError(f"Unsupported benchmark source: {source}")


async def benchmark_scrcpy_raw_stream(
    *,
    serial: str = "",
    adb_path: str = "adb",
    samples: int = 5,
    nudge_key: int | None = None,
    source_factory: Callable[[], ScrcpyRawStreamFrameSource] | None = None,
) -> BenchmarkResult:
    stop_nudge = threading.Event()
    nudge_thread = _start_nudge_thread(
        serial=serial,
        adb_path=adb_path,
        key=int(nudge_key) if nudge_key is not None else None,
        stop=stop_nudge,
    )
    source = source_factory() if source_factory else ScrcpyRawStreamFrameSource(
        serial=serial,
        adb_path=adb_path,
        include_png=False,
        fallback_to_adb=False,
    )
    timings: list[float] = []
    try:
        warmup = await source.latest_frame()
        last_ts = warmup.timestamp_ms
        for _ in range(max(1, int(samples or 1))):
            started = perf_counter()
            frame = await _wait_for_fresh_frame(source, previous_timestamp_ms=last_ts, timeout=2.0)
            elapsed = (perf_counter() - started) * 1000.0
            timings.append(elapsed)
            last_ts = frame.timestamp_ms
    finally:
        stop_nudge.set()
        if nudge_thread is not None:
            nudge_thread.join(timeout=1)
        source.close()
    avg = statistics.fmean(timings)
    p95 = _percentile(timings, 0.95)
    status, recommendation = classify_stream_latency(avg)
    return BenchmarkResult(
        name="scrcpy_raw_stream",
        samples=len(timings),
        avg_ms=round(avg, 3),
        p95_ms=round(p95, 3),
        max_ms=round(max(timings), 3),
        target_ms=45.0,
        status=status,
        recommendation=recommendation,
    )


async def _wait_for_fresh_frame(
    source: ScrcpyRawStreamFrameSource,
    *,
    previous_timestamp_ms: int,
    timeout: float,
):
    deadline = time.monotonic() + max(0.1, timeout)
    last_frame = None
    while time.monotonic() < deadline:
        frame = await source.latest_frame()
        last_frame = frame
        if frame.timestamp_ms != previous_timestamp_ms:
            return frame
        await asyncio.sleep(0.005)
    if last_frame is not None:
        return last_frame
    return await source.latest_frame()


def _start_nudge_thread(
    *,
    serial: str,
    adb_path: str,
    key: int | None,
    stop: threading.Event,
) -> threading.Thread | None:
    if key is None:
        return None

    def _loop() -> None:
        while not stop.is_set():
            cmd = [adb_path]
            if serial:
                cmd += ["-s", serial]
            cmd += ["shell", "input", "keyevent", str(key)]
            try:
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            except Exception:
                pass
            stop.wait(0.25)

    thread = threading.Thread(target=_loop, daemon=True)
    thread.start()
    return thread


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
