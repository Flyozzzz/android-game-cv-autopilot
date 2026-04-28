#!/usr/bin/env python3
"""Validate game profiles against a connected Android device."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.game_profiles import list_game_profiles  # noqa: E402
from core.profile_live_validation import validate_profiles_live, write_promoted_profile  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run evidence-backed live validation for game profiles.")
    parser.add_argument("--serial", required=True, help="ADB serial for the test device.")
    parser.add_argument("--adb", default="adb", help="adb binary path.")
    parser.add_argument("--profile", action="append", default=[], help="Profile id/package to validate. Repeatable. Defaults to all profiles.")
    parser.add_argument("--output", default="reports/profile_validation", help="Report output directory.")
    parser.add_argument("--no-explore", action="store_true", help="Only launch/capture; skip safe swipe exploration.")
    parser.add_argument(
        "--promote",
        choices=("none", "validated", "proven"),
        default="none",
        help="Write passed profile evidence back to dashboard/profiles. Use proven only for the claimed scope.",
    )
    parser.add_argument("--profiles-dir", default="dashboard/profiles", help="Profile JSON output directory for --promote.")
    args = parser.parse_args()

    summary = validate_profiles_live(
        serial=args.serial,
        profile_ids=args.profile,
        adb_path=args.adb,
        output_root=args.output,
        explore=not args.no_explore,
    )
    if args.promote != "none":
        profiles = {profile.id: profile for profile in list_game_profiles()}
        profiles.update({profile.package: profile for profile in list_game_profiles()})
        written = []
        for report in summary["profiles"]:
            profile = profiles.get(report["profile_id"]) or profiles.get(report["package"])
            if not profile or report["status"] != "passed":
                continue
            written.append(str(write_promoted_profile(profile, report, output_dir=args.profiles_dir, status=args.promote)))
        summary["promoted_profiles"] = written
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
