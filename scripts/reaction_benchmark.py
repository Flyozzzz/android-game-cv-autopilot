#!/usr/bin/env python3
"""Measure ADB capture latency for reaction-speed decisions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.reaction_benchmark import benchmark_capture_source  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark Android frame capture latency.")
    parser.add_argument("--serial", default="", help="ADB serial. Defaults to adb's selected device.")
    parser.add_argument("--adb", default="adb", help="adb binary path.")
    parser.add_argument("--samples", type=int, default=5, help="Number of screenshots.")
    parser.add_argument(
        "--source",
        choices=("adb", "adb_raw"),
        default="adb",
        help="Capture backend to benchmark.",
    )
    args = parser.parse_args()
    result = benchmark_capture_source(
        source=args.source,
        serial=args.serial,
        adb_path=args.adb,
        samples=args.samples,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0 if result.status in {"fast", "usable"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
