#!/usr/bin/env python3
"""Run local environment diagnostics for Android Game CV Autopilot."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.setup_doctor import doctor_report_markdown, run_setup_doctor  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Check local Android autopilot setup.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.add_argument("--latency", action="store_true", help="Measure ADB screencap latency when a device is connected.")
    args = parser.parse_args()
    result = run_setup_doctor(include_latency=args.latency)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(doctor_report_markdown(result))
    return 1 if result["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
