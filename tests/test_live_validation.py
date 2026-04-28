import subprocess

from core.autobuilder.live_validation import run_live_validation
from core.autobuilder.safety_policy import SafetyPolicy


def test_live_validation_runs_launch_and_reports_activity():
    def runner(args, timeout):
        joined = " ".join(args)
        if "pm path com.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"package:/data/app/base.apk\n", stderr=b"")
        if "dumpsys package com.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"versionName=1\nversionCode=2 minSdk=23\n", stderr=b"")
        if "dumpsys window windows" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"mCurrentFocus=Window{u0 com.game/.Main}\n", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")

    report = run_live_validation(
        {
            "profile": {"package": "com.game", "runtime": {"fast_gameplay": "local_only"}},
            "scenario": {"steps": [{"type": "enter_fast_gameplay"}]},
        },
        runner=runner,
        policy=SafetyPolicy(),
    )

    assert report["status"] == "passed"
    assert report["metrics"]["fast_gameplay_llm_calls"] == 0
    assert report["actions"][0]["type"] == "launch_app"
