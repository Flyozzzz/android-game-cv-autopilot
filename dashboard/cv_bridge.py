"""Dashboard CV planning and safe ADB execution helpers."""
from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import asdict
from typing import Any, Callable

from core.cv_autopilot import CVAutopilot, record_ui_action_plan_trace
from core.cv_engine import CVEngine


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


def _default_runner(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
    )


def _adb_text_arg(text: str) -> str:
    replacements = {
        " ": "%s",
        "&": r"\&",
        "|": r"\|",
        "<": r"\<",
        ">": r"\>",
        "(": r"\(",
        ")": r"\)",
        ";": r"\;",
        "*": r"\*",
        "'": r"\'",
        '"': r'\"',
        "`": r"\`",
        "\\": r"\\\\",
        "!": r"\!",
        "$": r"\$",
    }
    return "".join(replacements.get(ch, ch) for ch in str(text))


class DashboardAdbAction:
    """Minimal async action interface used by CVAutopilot over host ADB."""

    def __init__(
        self,
        serial: str,
        *,
        adb_path: str = "adb",
        runner: CommandRunner | None = None,
    ):
        self.serial = serial
        self.adb_path = adb_path
        self.runner = runner or _default_runner
        self._real_screen_w = 1080
        self._real_screen_h = 2400

    def _adb_cmd(self, *args: object) -> list[str]:
        cmd = [self.adb_path]
        if self.serial:
            cmd += ["-s", self.serial]
        cmd += [str(arg) for arg in args]
        return cmd

    async def _run(self, *args: object, timeout: int = 15) -> subprocess.CompletedProcess:
        cmd = self._adb_cmd(*args)
        return await asyncio.to_thread(self.runner, cmd, timeout)

    async def _run_adb(self, *args: object, timeout: int | None = None) -> str:
        proc = await self._run(*args, timeout=timeout or 15)
        return proc.stdout.decode(errors="ignore").strip()

    async def screenshot(self) -> bytes:
        proc = await self._run("exec-out", "screencap", "-p", timeout=20)
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="ignore").strip() or "ADB screencap failed")
        data = proc.stdout
        if not data.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("ADB screencap did not return PNG data")
        self._real_screen_w, self._real_screen_h = CVEngine._get_png_dimensions(data)
        return data

    async def tap(self, x: int, y: int, pause: float = 0.3):
        await self._run("shell", "input", "tap", int(x), int(y), timeout=8)
        if pause > 0:
            await asyncio.sleep(pause)

    async def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 350):
        await self._run("shell", "input", "swipe", int(x1), int(y1), int(x2), int(y2), int(duration_ms), timeout=10)

    async def swipe_up(self):
        w, h = self._real_screen_w, self._real_screen_h
        await self.swipe(w // 2, int(h * 0.75), w // 2, int(h * 0.30), 400)

    async def swipe_down(self):
        w, h = self._real_screen_w, self._real_screen_h
        await self.swipe(w // 2, int(h * 0.30), w // 2, int(h * 0.75), 400)

    async def type_text(self, text: str, pause: float = 0.3):
        await self._run("shell", "input", "text", _adb_text_arg(text), timeout=10)
        if pause > 0:
            await asyncio.sleep(pause)

    async def clear_field(self, max_chars: int = 180):
        await self._run("shell", "input", "keyevent", "277", timeout=8)
        await self._run("shell", "input", "keyevent", "67", timeout=8)

    async def press_back(self):
        await self._run("shell", "input", "keyevent", "4", timeout=8)

    async def press_home(self):
        await self._run("shell", "input", "keyevent", "3", timeout=8)

    async def press_enter(self):
        await self._run("shell", "input", "keyevent", "66", timeout=8)

    async def press_tab(self):
        await self._run("shell", "input", "keyevent", "61", timeout=8)


def _models_from_payload(payload: dict[str, Any]) -> list[str] | None:
    raw = payload.get("models")
    if isinstance(raw, str):
        models = [item.strip() for item in raw.split(",") if item.strip()]
        return models or None
    if isinstance(raw, list):
        models = [str(item).strip() for item in raw if str(item).strip()]
        return models or None
    return None


def _first_nonblank(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def require_vision_api_key(api_key: str = "") -> str:
    key = str(api_key or "").strip()
    if not key:
        raise RuntimeError(
            "OpenRouter / Vision API key is required. Enter it in Keys and provider "
            "credentials or set OPENROUTER_API_KEY."
        )
    return key


async def plan_cv_action(
    *,
    serial: str,
    goal: str,
    values: dict[str, str] | None = None,
    recent_actions: list[str] | None = None,
    api_key: str = "",
    models: list[str] | None = None,
    adb_path: str = "adb",
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    api_key = require_vision_api_key(api_key)
    action = DashboardAdbAction(serial, adb_path=adb_path, runner=runner)
    screenshot = await action.screenshot()
    async with CVEngine(api_key=api_key or None, models=models) as cv:
        plan = await cv.plan_next_ui_action(
            screenshot,
            goal=goal,
            available_values=values or {},
            recent_actions=recent_actions or [],
        )
    record_ui_action_plan_trace(
        plan,
        screenshot,
        goal=goal,
        outcome="planned",
        frame_source="adb",
        policy_result="planned",
    )
    return {
        "serial": serial,
        "plan": plan.model_dump(),
        "screen": {
            "width": action._real_screen_w,
            "height": action._real_screen_h,
            "png_bytes": len(screenshot),
        },
    }


async def run_cv_goal(
    *,
    serial: str,
    goal: str,
    values: dict[str, str] | None = None,
    max_steps: int = 12,
    api_key: str = "",
    models: list[str] | None = None,
    adb_path: str = "adb",
    runner: CommandRunner | None = None,
) -> dict[str, Any]:
    api_key = require_vision_api_key(api_key)
    action = DashboardAdbAction(serial, adb_path=adb_path, runner=runner)
    max_steps = max(1, min(int(max_steps or 12), 60))
    async with CVEngine(api_key=api_key or None, models=models) as cv:
        result = await CVAutopilot(
            action=action,
            cv=cv,
            max_steps=max_steps,
            allow_risky_actions=False,
            stop_on_risky_action=True,
        ).run(goal, values or {})
    return {
        "serial": serial,
        "status": result.status,
        "ok": result.ok,
        "reason": result.reason,
        "steps": [asdict(step) for step in result.steps],
    }


def payload_values(payload: dict[str, Any]) -> dict[str, str]:
    values = payload.get("values") or {}
    if not isinstance(values, dict):
        return {}
    return {str(key): str(value) for key, value in values.items()}


def payload_recent_actions(payload: dict[str, Any]) -> list[str]:
    recent = payload.get("recentActions") or payload.get("recent_actions") or []
    if not isinstance(recent, list):
        return []
    return [str(item) for item in recent]


def payload_api_key(payload: dict[str, Any]) -> str:
    return _first_nonblank(
        payload.get("openrouterKey"),
        payload.get("apiKey"),
        os.getenv("OPENROUTER_API_KEY", ""),
    )


def payload_models(payload: dict[str, Any]) -> list[str] | None:
    return _models_from_payload(payload)
