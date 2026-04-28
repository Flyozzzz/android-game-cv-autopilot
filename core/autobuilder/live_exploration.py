"""Live multi-step ADB exploration for prompt-built autopilots."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

from PIL import Image

from core.autobuilder.exploration_state import ExplorationState, ExplorationStep
from core.autobuilder.policy_guard import PolicyGuard
from core.autobuilder.safety_policy import SafetyPolicy
from core.autobuilder.screen_graph import ScreenGraph


CommandRunner = Callable[[list[str], int], subprocess.CompletedProcess]


@dataclass(frozen=True)
class LiveExplorationResult:
    graph: ScreenGraph
    state: ExplorationState
    frame_paths: list[Path]
    actions: list[dict[str, Any]]
    failures: list[str]

    def to_report(self) -> dict[str, Any]:
        return {
            "status": self.state.status,
            "actions": list(self.actions),
            "failures": list(self.failures),
            "frames": [str(path) for path in self.frame_paths],
            "screen_graph": self.graph.to_dict(),
            "metrics": {
                "actions": len(self.actions),
                "frames": len(self.frame_paths),
                "screens": len(self.graph.screens),
                "transitions": len(self.graph.transitions),
            },
        }


def default_live_exploration_actions() -> list[dict[str, Any]]:
    return [
        {"type": "swipe", "direction": "up", "name": "safe_scroll_up"},
        {"type": "swipe", "direction": "down", "name": "safe_scroll_down"},
        {"type": "swipe", "direction": "left", "name": "safe_swipe_left"},
        {"type": "swipe", "direction": "right", "name": "safe_swipe_right"},
    ]


def run_live_exploration(
    *,
    serial: str,
    adb_path: str = "adb",
    actions: list[dict[str, Any]] | None = None,
    output_dir: str | Path,
    policy: SafetyPolicy | None = None,
    runner: CommandRunner | None = None,
    settle_seconds: float = 0.35,
) -> LiveExplorationResult:
    if not serial:
        raise RuntimeError("live exploration requires an ADB serial")
    runner = runner or _run
    guard = PolicyGuard(policy or SafetyPolicy())
    graph = ScreenGraph()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    failures: list[str] = []
    executed: list[dict[str, Any]] = []
    steps: list[ExplorationStep] = []
    frame_paths: list[Path] = []

    previous_screen_id = _capture_screen(
        graph=graph,
        frame_paths=frame_paths,
        serial=serial,
        adb_path=adb_path,
        runner=runner,
        output=output,
        index=0,
        action_name="initial",
    )
    for index, action in enumerate(actions or default_live_exploration_actions(), start=1):
        decision = guard.require_allowed(action)
        try:
            _execute_action(serial=serial, adb_path=adb_path, runner=runner, action=action)
            time.sleep(max(0.0, settle_seconds))
            current_screen_id = _capture_screen(
                graph=graph,
                frame_paths=frame_paths,
                serial=serial,
                adb_path=adb_path,
                runner=runner,
                output=output,
                index=index,
                action_name=str(action.get("name") or action.get("type") or "action"),
            )
            graph.add_transition(previous_screen_id, str(action.get("name") or action.get("type") or "action"), current_screen_id)
            steps.append(
                ExplorationStep(
                    index=index,
                    screen_id=previous_screen_id,
                    action=dict(action),
                    result_screen_id=current_screen_id,
                    policy_result=decision.reason,
                )
            )
            executed.append({**dict(action), "result_screen_id": current_screen_id})
            previous_screen_id = current_screen_id
        except Exception as exc:
            failures.append(f"{action.get('name') or action.get('type')}: {exc}")
            break

    status = "ok" if not failures and executed else "failed"
    state = ExplorationState(status=status, steps=steps, failures=failures, screenshots=[str(path) for path in frame_paths])
    return LiveExplorationResult(graph=graph, state=state, frame_paths=frame_paths, actions=executed, failures=failures)


def _capture_screen(
    *,
    graph: ScreenGraph,
    frame_paths: list[Path],
    serial: str,
    adb_path: str,
    runner: CommandRunner,
    output: Path,
    index: int,
    action_name: str,
) -> str:
    png = _screenshot(serial=serial, adb_path=adb_path, runner=runner)
    path = output / f"frame_{index:03d}.png"
    path.write_bytes(png)
    frame_paths.append(path)
    width, height = _image_size(png)
    texts = _visible_texts(serial=serial, adb_path=adb_path, runner=runner)
    screen_id = f"screen_{index + 1:03d}"
    graph.add_screen(
        screen_id=screen_id,
        screen_hash=_hash(png),
        screen_type=_screen_type(texts),
        texts=texts,
        elements=texts[:20],
        safe_actions=[action_name] if action_name != "initial" else [],
        risky_actions=[],
    )
    return screen_id if width > 0 and height > 0 else screen_id


def _execute_action(*, serial: str, adb_path: str, runner: CommandRunner, action: dict[str, Any]) -> None:
    action_type = str(action.get("type") or "").strip().lower()
    if action_type == "wait":
        time.sleep(float(action.get("seconds") or 0.5))
        return
    if action_type == "press":
        key = str(action.get("key") or "back").strip().lower()
        keycode = {"back": "4", "home": "3", "enter": "66"}.get(key, key)
        proc = runner([adb_path, "-s", serial, "shell", "input", "keyevent", keycode], 10)
        _require_ok(proc)
        return
    if action_type == "tap":
        x = int(action.get("x") or 0)
        y = int(action.get("y") or 0)
        proc = runner([adb_path, "-s", serial, "shell", "input", "tap", str(x), str(y)], 10)
        _require_ok(proc)
        return
    if action_type == "swipe":
        x1, y1, x2, y2, duration = _swipe_points(action)
        proc = runner([adb_path, "-s", serial, "shell", "input", "swipe", str(x1), str(y1), str(x2), str(y2), str(duration)], 10)
        _require_ok(proc)
        return
    raise RuntimeError(f"unsupported live exploration action: {action_type}")


def _swipe_points(action: dict[str, Any]) -> tuple[int, int, int, int, int]:
    width = int(action.get("screen_width") or 1080)
    height = int(action.get("screen_height") or 2400)
    direction = str(action.get("direction") or "up").strip().lower()
    duration = int(action.get("duration_ms") or 300)
    left = int(width * 0.30)
    right = int(width * 0.70)
    top = int(height * 0.35)
    bottom = int(height * 0.70)
    mid_x = width // 2
    mid_y = height // 2
    if direction == "down":
        return mid_x, top, mid_x, bottom, duration
    if direction == "left":
        return right, mid_y, left, mid_y, duration
    if direction == "right":
        return left, mid_y, right, mid_y, duration
    return mid_x, bottom, mid_x, top, duration


def _screenshot(*, serial: str, adb_path: str, runner: CommandRunner) -> bytes:
    proc = runner([adb_path, "-s", serial, "exec-out", "screencap", "-p"], 20)
    _require_ok(proc)
    data = proc.stdout if isinstance(proc.stdout, bytes) else str(proc.stdout).encode()
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RuntimeError("ADB screencap did not return PNG")
    return data


def _visible_texts(*, serial: str, adb_path: str, runner: CommandRunner) -> list[str]:
    proc = runner([adb_path, "-s", serial, "exec-out", "uiautomator", "dump", "/dev/tty"], 25)
    if proc.returncode != 0:
        return []
    text = _decode(proc.stdout)
    if "<hierarchy" not in text:
        return []
    xml_start = text.find("<hierarchy")
    xml_end = text.rfind("</hierarchy>")
    if xml_start > 0:
        text = text[xml_start:]
    if xml_end >= 0:
        text = text[:xml_end - xml_start + len("</hierarchy>") if xml_start > 0 else xml_end + len("</hierarchy>")]
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    values: list[str] = []
    for node in root.iter("node"):
        for key in ("text", "content-desc", "resource-id"):
            value = str(node.attrib.get(key) or "").strip()
            if value:
                values.append(value)
    return _dedupe(values)


def _image_size(png: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(png)) as image:
        return image.size


def _screen_type(texts: list[str]) -> str:
    haystack = " ".join(texts).lower()
    if any(word in haystack for word in ("buy", "purchase", "subscribe", "оплат", "купить")):
        return "purchase"
    if any(word in haystack for word in ("sign in", "login", "account", "google")):
        return "login"
    if any(word in haystack for word in ("settings", "play", "continue", "skip", "настрой")):
        return "menu"
    return "unknown"


def _hash(data: bytes) -> str:
    return hashlib.sha256(data or b"").hexdigest()[:16]


def _decode(data: bytes | str) -> str:
    return data.decode(errors="ignore") if isinstance(data, bytes) else str(data or "")


def _require_ok(proc: subprocess.CompletedProcess) -> None:
    if proc.returncode != 0:
        raise RuntimeError(_decode(proc.stderr).strip() or "adb command failed")


def _dedupe(values: list[str]) -> list[str]:
    seen = set()
    result = []
    for value in values:
        normalized = re.sub(r"\s+", " ", value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
