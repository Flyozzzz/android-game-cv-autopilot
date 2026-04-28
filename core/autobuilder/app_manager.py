"""Controlled app lifecycle manager for builder flows."""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from core.autobuilder.policy_guard import PolicyGuard
from core.autobuilder.safety_policy import SafetyPolicy


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


@dataclass(frozen=True)
class AppInfo:
    package: str
    installed: bool = False
    version_name: str = ""
    version_code: str = ""
    current_activity: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class AppManager:
    def __init__(
        self,
        *,
        serial: str = "",
        adb_path: str = "adb",
        policy: SafetyPolicy | None = None,
        runner: CommandRunner | None = None,
        trusted_apk_roots: list[str | Path] | None = None,
        test_device: bool = True,
    ):
        self.serial = serial
        self.adb_path = adb_path
        self.guard = PolicyGuard(policy or SafetyPolicy())
        self.runner = runner or _default_runner
        self.trusted_apk_roots = [Path(path).resolve() for path in (trusted_apk_roots or [])]
        self.test_device = test_device

    def _cmd(self, *args: object) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += [str(arg) for arg in args]
        return cmd

    def check_installed(self, package: str) -> bool:
        proc = self.runner(self._cmd("shell", "pm", "path", package), 10)
        return proc.returncode == 0 and bool(proc.stdout)

    def get_package_info(self, package: str) -> AppInfo:
        installed = self.check_installed(package)
        version_name = version_code = ""
        if installed:
            proc = self.runner(self._cmd("shell", "dumpsys", "package", package), 15)
            text = _decode(proc.stdout)
            version_name = _field(text, "versionName=")
            version_code = _field(text, "versionCode=")
        return AppInfo(package=package, installed=installed, version_name=version_name, version_code=version_code)

    def get_current_activity(self) -> str:
        proc = self.runner(self._cmd("shell", "dumpsys", "window", "windows"), 10)
        text = _decode(proc.stdout)
        for marker in ("mCurrentFocus=", "mFocusedApp="):
            if marker in text:
                return text.split(marker, 1)[1].splitlines()[0].strip()
        return ""

    def launch_app(self, package: str) -> AppInfo:
        self.guard.require_allowed({"type": "launch_app", "package": package})
        proc = self.runner(self._cmd("shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"), 15)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or f"failed to launch {package}")
        info = self.get_package_info(package)
        return AppInfo(**{**info.to_dict(), "current_activity": self.get_current_activity()})

    def stop_app(self, package: str) -> dict:
        self.guard.require_allowed({"type": "stop_app", "package": package})
        proc = self.runner(self._cmd("shell", "am", "force-stop", package), 10)
        return {"ok": proc.returncode == 0, "stderr": _decode(proc.stderr)}

    def install_apk(self, apk_path: str | Path) -> dict:
        path = Path(apk_path).expanduser().resolve()
        self.guard.require_allowed({"type": "install_apk", "source": str(path)})
        if not path.exists() or path.suffix.lower() != ".apk":
            raise RuntimeError("install source must be an existing APK")
        if self.trusted_apk_roots and not any(_is_relative_to(path, root) for root in self.trusted_apk_roots):
            raise RuntimeError("APK source is not allowlisted")
        proc = self.runner(self._cmd("install", "-r", str(path)), 120)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "adb install failed")
        return {"installed": True, "apk": str(path)}

    def reset_app_data(self, package: str) -> dict:
        self.guard.require_allowed({"type": "reset_data", "package": package})
        if not self.test_device:
            raise RuntimeError("reset app data is allowed only on test devices/emulators")
        proc = self.runner(self._cmd("shell", "pm", "clear", package), 30)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "pm clear failed")
        return {"reset": True, "package": package}


def _default_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _decode(data: bytes | str) -> str:
    return data.decode(errors="ignore").strip() if isinstance(data, bytes) else str(data or "").strip()


def _field(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split()[0].strip()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
