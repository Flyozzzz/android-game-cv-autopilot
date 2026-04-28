#!/usr/bin/env python3
"""Run a profile/device benchmark matrix and save a JSON report."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.benchmark_matrix import run_benchmark_matrix  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run benchmark matrix for Android profiles.")
    parser.add_argument("--serial", required=True, help="ADB serial for the test device.")
    parser.add_argument("--adb", default="adb", help="adb binary path.")
    parser.add_argument("--profile", action="append", default=[], help="Profile id/package to test. Repeatable. Defaults to all profiles.")
    parser.add_argument("--runs", type=int, default=20, help="Runs per profile. Use 20 for release evidence.")
    parser.add_argument("--output", default="reports/benchmark_matrix", help="Report output directory.")
    parser.add_argument("--no-explore", action="store_true", help="Only launch/capture; skip safe exploration gestures.")
    args = parser.parse_args()
    matrix = run_benchmark_matrix(
        serial=args.serial,
        profile_ids=args.profile,
        runs=args.runs,
        adb_path=args.adb,
        output_root=args.output,
        explore=not args.no_explore,
    )
    print(json.dumps(matrix, ensure_ascii=False, indent=2))
    return 0 if matrix["summary"]["failed_profiles"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
