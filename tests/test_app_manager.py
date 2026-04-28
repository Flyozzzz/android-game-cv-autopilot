import subprocess

import pytest

from core.autobuilder.app_manager import AppManager


class Runner:
    def __init__(self):
        self.commands = []

    def __call__(self, args, timeout):
        self.commands.append(args)
        joined = " ".join(args)
        if "pm path com.example.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"package:/data/app/base.apk\n", stderr=b"")
        if "dumpsys package com.example.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"versionName=1.2\nversionCode=3 minSdk=23\n", stderr=b"")
        if "dumpsys window windows" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"mCurrentFocus=Window{u0 com.example.game/.Main}\n", stderr=b"")
        if "cmd package resolve-activity --brief com.example.game" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"com.example.game/.Main\n", stderr=b"")
        if "am start -n com.example.game/.Main" in joined:
            return subprocess.CompletedProcess(args, 0, stdout=b"Starting: Intent", stderr=b"")
        return subprocess.CompletedProcess(args, 0, stdout=b"", stderr=b"")


def test_app_manager_launches_installed_package_and_reads_activity():
    runner = Runner()
    manager = AppManager(serial="device", runner=runner)

    assert manager.check_installed("com.example.game")
    info = manager.launch_app("com.example.game")

    assert info.installed
    assert info.version_name == "1.2"
    assert "com.example.game/.Main" in info.current_activity
    assert any("resolve-activity" in cmd for cmd in runner.commands)
    assert any("am" in cmd and "start" in cmd for cmd in runner.commands)
    assert not any("monkey" in cmd for cmd in runner.commands)


def test_app_manager_retries_retryable_adb_races():
    class FlakyRunner(Runner):
        def __init__(self):
            super().__init__()
            self.start_attempts = 0

        def __call__(self, args, timeout):
            joined = " ".join(args)
            if "am start -n com.example.game/.Main" in joined:
                self.commands.append(args)
                self.start_attempts += 1
                if self.start_attempts == 1:
                    return subprocess.CompletedProcess(args, 1, stdout=b"", stderr=b"device offline")
                return subprocess.CompletedProcess(args, 0, stdout=b"Starting", stderr=b"")
            return super().__call__(args, timeout)

    runner = FlakyRunner()
    manager = AppManager(serial="device", runner=runner)

    info = manager.launch_app("com.example.game")

    assert info.installed is True
    assert runner.start_attempts == 2


def test_app_manager_review_gates_install_and_reset(tmp_path):
    manager = AppManager(runner=Runner())
    apk = tmp_path / "game.apk"
    apk.write_bytes(b"apk")

    with pytest.raises(RuntimeError, match="Review required"):
        manager.install_apk(apk)
    with pytest.raises(RuntimeError, match="Review required"):
        manager.reset_app_data("com.example.game")
