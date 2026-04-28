"""Controlled app lifecycle manager for builder flows."""
from __future__ import annotations

import subprocess
import time
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
        proc = self._run_adb("shell", "pm", "path", package, timeout=10)
        return proc.returncode == 0 and bool(proc.stdout)

    def get_package_info(self, package: str) -> AppInfo:
        installed = self.check_installed(package)
        version_name = version_code = ""
        if installed:
            proc = self._run_adb("shell", "dumpsys", "package", package, timeout=15)
            text = _decode(proc.stdout)
            version_name = _field(text, "versionName=")
            version_code = _field(text, "versionCode=")
        return AppInfo(package=package, installed=installed, version_name=version_name, version_code=version_code)

    def get_current_activity(self) -> str:
        proc = self._run_adb("shell", "dumpsys", "window", "windows", timeout=10)
        text = _decode(proc.stdout)
        for marker in ("mCurrentFocus=", "mFocusedApp="):
            if marker in text:
                return text.split(marker, 1)[1].splitlines()[0].strip()
        return ""

    def resolve_launch_activity(self, package: str) -> str:
        proc = self._run_adb("shell", "cmd", "package", "resolve-activity", "--brief", package, timeout=10)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or f"failed to resolve launcher activity for {package}")
        component = _parse_activity_component(_decode(proc.stdout), package)
        if not component:
            raise RuntimeError(f"could not resolve launcher activity for {package}")
        return component

    def launch_app(self, package: str) -> AppInfo:
        self.guard.require_allowed({"type": "launch_app", "package": package})
        component = self.resolve_launch_activity(package)
        proc = self._run_adb("shell", "am", "start", "-n", component, timeout=15, retries=2)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or f"failed to launch {package}")
        info = self.get_package_info(package)
        return AppInfo(**{**info.to_dict(), "current_activity": self.get_current_activity()})

    def stop_app(self, package: str) -> dict:
        self.guard.require_allowed({"type": "stop_app", "package": package})
        proc = self._run_adb("shell", "am", "force-stop", package, timeout=10)
        return {"ok": proc.returncode == 0, "stderr": _decode(proc.stderr)}

    def install_apk(self, apk_path: str | Path) -> dict:
        path = Path(apk_path).expanduser().resolve()
        self.guard.require_allowed({"type": "install_apk", "source": str(path)})
        if not path.exists() or path.suffix.lower() != ".apk":
            raise RuntimeError("install source must be an existing APK")
        if self.trusted_apk_roots and not any(_is_relative_to(path, root) for root in self.trusted_apk_roots):
            raise RuntimeError("APK source is not allowlisted")
        proc = self._run_adb("install", "-r", str(path), timeout=120, retries=1)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "adb install failed")
        return {"installed": True, "apk": str(path)}

    def reset_app_data(self, package: str) -> dict:
        self.guard.require_allowed({"type": "reset_data", "package": package})
        if not self.test_device:
            raise RuntimeError("reset app data is allowed only on test devices/emulators")
        proc = self._run_adb("shell", "pm", "clear", package, timeout=30)
        if proc.returncode != 0:
            raise RuntimeError(_decode(proc.stderr) or "pm clear failed")
        return {"reset": True, "package": package}

    def _run_adb(self, *args: object, timeout: int = 10, retries: int = 2, backoff_seconds: float = 0.20) -> subprocess.CompletedProcess:
        cmd = self._cmd(*args)
        attempts = max(1, int(retries or 0) + 1)
        last: subprocess.CompletedProcess | None = None
        for attempt in range(attempts):
            try:
                proc = self.runner(cmd, timeout)
            except subprocess.TimeoutExpired as exc:
                proc = subprocess.CompletedProcess(cmd, 124, stdout=exc.stdout or b"", stderr=exc.stderr or b"timeout")
            last = proc
            if proc.returncode == 0:
                return proc
            if attempt + 1 < attempts and _retryable_adb_error(_decode(proc.stderr) or _decode(proc.stdout)):
                time.sleep(max(0.0, backoff_seconds) * (2 ** attempt))
                continue
            return proc
        return last or subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"adb command failed")


def _default_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _decode(data: bytes | str) -> str:
    return data.decode(errors="ignore").strip() if isinstance(data, bytes) else str(data or "").strip()


def _field(text: str, marker: str) -> str:
    if marker not in text:
        return ""
    return text.split(marker, 1)[1].split()[0].strip()


def _parse_activity_component(output: str, package: str) -> str:
    lines = [line.strip() for line in str(output or "").splitlines() if line.strip()]
    for line in reversed(lines):
        if "/" not in line or line.lower().startswith("no activity"):
            continue
        component = line.split()[-1]
        if component.startswith("."):
            return f"{package}/{component}"
        if component.startswith(f"{package}/"):
            return component
        if "/" in component:
            return component
    return ""


def _retryable_adb_error(message: str) -> bool:
    lowered = str(message or "").lower()
    if not lowered:
        return True
    return any(
        marker in lowered
        for marker in (
            "timeout",
            "device offline",
            "device not found",
            "more than one device",
            "closed",
            "temporarily unavailable",
            "cannot connect",
        )
    )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
