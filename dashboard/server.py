"""Local web dashboard for configuring and controlling the autopilot."""
from __future__ import annotations

import asyncio
from dataclasses import asdict
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
import os
from pathlib import Path
import shutil
import signal
import subprocess
import secrets
import sys
import threading
import time
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = Path(__file__).resolve().parent / "static"
RUNS_DIR = Path(__file__).resolve().parent / "runs"
PRESETS_DIR = Path(__file__).resolve().parent / "presets"
LATEST_PRESET = PRESETS_DIR / "latest.json"
RECORDINGS_DIR = Path(__file__).resolve().parent / "recordings"
PROFILES_DIR = Path(__file__).resolve().parent / "profiles"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import config  # noqa: E402
from core.cv_prompt_templates import (  # noqa: E402
    INSTALL_GOAL_TEMPLATE,
    PURCHASE_GOAL_TEMPLATE,
    TUTORIAL_GOAL_TEMPLATE,
)
from core.game_profiles import game_profile_from_mapping, list_game_profiles  # noqa: E402
from core.profile_validation import profile_validation_summary  # noqa: E402
from dashboard.cv_bridge import (  # noqa: E402
    payload_api_key,
    payload_models,
    payload_recent_actions,
    payload_values,
    plan_cv_action,
    run_cv_goal,
)
from dashboard.api_vision import (  # noqa: E402
    create_roi_from_payload,
    export_label_from_payload,
    list_template_library,
    save_template_from_payload,
    vision_inspector_payload,
)
from dashboard.api_builder import build_autopilot_from_payload, builder_state  # noqa: E402


ADB_PATH = os.getenv("ADB_PATH") or shutil.which("adb") or "adb"
RUN_LOCK = threading.Lock()
RUN_PROCESS: subprocess.Popen | None = None
RUN_LOG_PATH: Path | None = None
AUTH_LOCK = threading.Lock()
SESSIONS: dict[str, dict[str, object]] = {}
SESSION_COOKIE_NAME = "autopilot_dashboard_session"


FARMS = ("local", "genymotion", "browserstack", "lambdatest")
STAGES = ("google", "pay", "install", "tutorial", "gameplay", "purchase_preview")
GOOGLE_REGISTER_METHODS = ("chrome", "cv", "web", "android")
INSTALL_METHODS = ("cv", "deterministic", "manual", "recorded")
TUTORIAL_METHODS = ("cv", "deterministic", "manual", "recorded")
GAMEPLAY_METHODS = ("auto", "fast", "manual", "recorded", "off")
PURCHASE_METHODS = ("cv", "manual")
PROJECT_EDITOR_ROOTS = (
    Path("dashboard/presets"),
    Path("dashboard/profiles"),
    Path("dashboard/recordings"),
    Path("dashboard/prompts"),
)
PROJECT_EDITOR_EXTENSIONS = {".json", ".md", ".txt", ".yaml", ".yml"}
EXCLUDED_DIR_NAMES = {
    ".claude",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "env",
    "legacy",
    "logs",
    "node_modules",
    "reports",
    "runs",
    "screenshots",
    "trace",
    "venv",
}
EXCLUDED_FILE_NAMES = {
    ".DS_Store",
    ".env",
    ".env.local",
    "credentials.json",
}
MAX_EDIT_FILE_BYTES = 768 * 1024


def _json_bytes(payload: object) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _run_command(args: list[str], *, timeout: int = 10) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as e:
        return 124, e.stdout or "", e.stderr or "timeout"
    except Exception as e:
        return 1, "", str(e)


def _adb_devices() -> list[dict[str, str]]:
    code, out, _ = _run_command([ADB_PATH, "devices", "-l"], timeout=6)
    if code != 0:
        return []
    devices: list[dict[str, str]] = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2:
            continue
        serial, state = parts[0], parts[1]
        details = " ".join(parts[2:])
        devices.append({"serial": serial, "state": state, "details": details})
    return devices


def _select_serial(requested: str = "") -> str:
    devices = [d for d in _adb_devices() if d["state"] == "device"]
    if requested:
        for device in devices:
            if device["serial"] == requested:
                return requested
        raise RuntimeError(f"ADB device not connected: {requested}")
    if not devices:
        raise RuntimeError("No Android device connected")
    return devices[0]["serial"]


def _latest_report() -> dict:
    path = ROOT / "reports" / "latest_run_report.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception as e:
        return {"error": str(e)}


def _load_preset() -> dict:
    if not LATEST_PRESET.exists():
        return {}
    try:
        return json.loads(LATEST_PRESET.read_text())
    except Exception:
        return {}


def _looks_like_secret(value: str) -> bool:
    value = (value or "").strip()
    return len(value) > 20 and "..." not in value


def _dashboard_auth_enabled() -> bool:
    return bool(getattr(config, "DASHBOARD_AUTH_ENABLED", True))


def _dashboard_username() -> str:
    return str(getattr(config, "DASHBOARD_USERNAME", "admin") or "admin")


def _dashboard_password() -> str:
    return str(getattr(config, "DASHBOARD_PASSWORD", "change-me") or "change-me")


def _dashboard_mcp_api_key() -> str:
    return str(getattr(config, "DASHBOARD_MCP_API_KEY", "change-me") or "change-me")


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in {"", "127.0.0.1", "localhost", "::1"}


def _unsafe_public_secret(value: str) -> bool:
    return str(value or "").strip().lower() in {"", "admin", "change-me", "changeme", "password"}


def _validate_dashboard_exposure(host: str) -> None:
    if _is_loopback_host(host):
        return
    if not _dashboard_auth_enabled():
        raise RuntimeError("DASHBOARD_AUTH_ENABLED=0 is not allowed when DASHBOARD_HOST is not loopback")
    if _unsafe_public_secret(_dashboard_password()):
        raise RuntimeError("Set a strong DASHBOARD_PASSWORD before binding dashboard outside localhost")
    if _unsafe_public_secret(_dashboard_mcp_api_key()):
        raise RuntimeError("Set a strong DASHBOARD_MCP_API_KEY before binding dashboard outside localhost")


def _login_matches(username: str, password: str) -> bool:
    return (
        hmac.compare_digest(str(username or ""), _dashboard_username())
        and hmac.compare_digest(str(password or ""), _dashboard_password())
    )


def _create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    ttl = int(getattr(config, "DASHBOARD_SESSION_TTL_SECONDS", 86400) or 86400)
    with AUTH_LOCK:
        SESSIONS[token] = {"username": username, "expires": time.time() + max(60, ttl)}
    return token


def _cookie_value(cookie_header: str, name: str) -> str:
    for part in str(cookie_header or "").split(";"):
        key, _, value = part.strip().partition("=")
        if key == name:
            return value
    return ""


def _session_authorized(cookie_header: str) -> bool:
    token = _cookie_value(cookie_header, SESSION_COOKIE_NAME)
    if not token:
        return False
    with AUTH_LOCK:
        session = SESSIONS.get(token)
        if not session:
            return False
        if float(session.get("expires") or 0) < time.time():
            SESSIONS.pop(token, None)
            return False
    return True


def _api_key_authorized(value: str) -> bool:
    expected = _dashboard_mcp_api_key()
    candidate = str(value or "").strip()
    if candidate.lower().startswith("bearer "):
        candidate = candidate[7:].strip()
    return bool(expected and hmac.compare_digest(candidate, expected))


def _is_public_path(path: str) -> bool:
    return path in {"/api/login", "/api/logout"} or path.startswith("/static/")


def _safe_recording_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return cleaned[:80] or f"recording_{int(time.time())}"


def _safe_profile_id(value: str) -> str:
    cleaned: list[str] = []
    last_dash = False
    for ch in value.strip().lower():
        if ch.isalnum():
            cleaned.append(ch)
            last_dash = False
        elif not last_dash:
            cleaned.append("-")
            last_dash = True
    profile_id = "".join(cleaned).strip("-")
    return profile_id[:80] or f"profile-{int(time.time())}"


def _safe_preset_name(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in name.strip())
    return cleaned[:80] or f"preset_{int(time.time())}"


def _custom_profile_path(profile_id: str) -> Path:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    return (PROFILES_DIR / f"{_safe_profile_id(profile_id)}.json").resolve()


def _preset_path(name: str) -> Path:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    return (PRESETS_DIR / f"{_safe_preset_name(name)}.json").resolve()


def _recording_files() -> list[dict[str, str]]:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, str]] = []
    for path in sorted(RECORDINGS_DIR.glob("*.json")):
        try:
            payload = json.loads(path.read_text())
            count = len(payload.get("actions", [])) if isinstance(payload, dict) else 0
        except Exception:
            count = 0
        items.append({
            "name": path.stem,
            "path": str(path.relative_to(ROOT)),
            "actions": str(count),
        })
    return items


def _profile_to_settings(profile: dict) -> dict:
    return {
        "gameProfile": profile.get("id", ""),
        "gameName": profile.get("name", ""),
        "gamePackage": profile.get("package", ""),
        "playerPrefix": profile.get("player_name_prefix") or "Player",
        "cvTutorialMaxSteps": profile.get("max_tutorial_steps") or "",
        "cvPurchaseMaxSteps": profile.get("max_purchase_steps") or "",
        "cvTutorialInstructions": "\n".join(profile.get("tutorial_hints") or ()),
        "cvPurchaseInstructions": "\n".join(profile.get("purchase_hints") or ()),
        "cvExtraBlockers": ",".join(profile.get("blocker_words") or ()),
    }


def _preset_files() -> list[dict]:
    PRESETS_DIR.mkdir(parents=True, exist_ok=True)
    presets: list[dict] = []
    for path in sorted(PRESETS_DIR.glob("*.json")):
        if path.name == "latest.json":
            continue
        try:
            settings = json.loads(path.read_text())
        except Exception:
            continue
        presets.append({
            "name": path.stem,
            "path": str(path.relative_to(ROOT)),
            "title": settings.get("title") or path.stem.replace("_", " "),
            "description": settings.get("description") or "",
            "settings": settings,
        })
    return presets


def _inside_root(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _is_excluded_relative_path(rel_path: Path) -> bool:
    parts = set(rel_path.parts)
    return bool(parts & EXCLUDED_DIR_NAMES) or rel_path.name in EXCLUDED_FILE_NAMES


def _is_project_editor_path(rel_path: Path) -> bool:
    return any(
        rel_path == root or _inside_root(rel_path, root)
        for root in PROJECT_EDITOR_ROOTS
    )


def _resolve_project_file(path_value: str, *, must_exist: bool = True) -> tuple[Path, str]:
    value = str(path_value or "").strip().replace("\\", "/")
    if not value:
        raise RuntimeError("File path is required")
    path = (ROOT / value).resolve()
    if not _inside_root(path, ROOT):
        raise RuntimeError("File path must stay inside the project")
    rel = path.relative_to(ROOT)
    if _is_excluded_relative_path(rel):
        raise RuntimeError("This file or folder is not editable from the dashboard")
    if not _is_project_editor_path(rel):
        allowed = ", ".join(root.as_posix() for root in PROJECT_EDITOR_ROOTS)
        raise RuntimeError(f"Only dashboard data files are editable here: {allowed}")
    if path.suffix.lower() not in PROJECT_EDITOR_EXTENSIONS:
        raise RuntimeError(f"Unsupported editable file type: {path.suffix or '(none)'}")
    if must_exist and (not path.exists() or not path.is_file()):
        raise RuntimeError(f"File not found: {rel.as_posix()}")
    if path.exists() and path.stat().st_size > MAX_EDIT_FILE_BYTES:
        raise RuntimeError("File is too large for dashboard editing")
    return path, rel.as_posix()


def _project_files() -> list[dict[str, object]]:
    files: list[dict[str, object]] = []
    for editable_root in PROJECT_EDITOR_ROOTS:
        walk_root = ROOT / editable_root
        if not walk_root.exists():
            continue
        for current, dir_names, file_names in os.walk(walk_root):
            current_path = Path(current)
            try:
                rel_dir = current_path.relative_to(ROOT)
            except ValueError:
                continue
            dir_names[:] = [
                name for name in sorted(dir_names)
                if name not in EXCLUDED_DIR_NAMES and name != ".Trash"
            ]
            if _is_excluded_relative_path(rel_dir):
                continue
            for file_name in sorted(file_names):
                path = current_path / file_name
                rel = path.relative_to(ROOT)
                if _is_excluded_relative_path(rel):
                    continue
                if path.suffix.lower() not in PROJECT_EDITOR_EXTENSIONS:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                if size > MAX_EDIT_FILE_BYTES:
                    continue
                files.append({
                    "path": rel.as_posix(),
                    "name": file_name,
                    "size": size,
                })
    return files


def _resolve_recording_path(path_value: str = "", name: str = "") -> Path:
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    if path_value:
        path = (ROOT / str(path_value).strip()).resolve()
    else:
        path = (RECORDINGS_DIR / f"{_safe_recording_name(name)}.json").resolve()
    if not _inside_root(path, RECORDINGS_DIR.resolve()):
        raise RuntimeError("Recording path must stay inside dashboard/recordings")
    if path.suffix.lower() != ".json":
        raise RuntimeError("Recording must be a JSON file")
    return path


def _active_run() -> dict:
    with RUN_LOCK:
        proc = RUN_PROCESS
        log_path = RUN_LOG_PATH
    if not proc:
        return {"running": False}
    return {
        "running": proc.poll() is None,
        "pid": proc.pid,
        "returncode": proc.poll(),
        "log_path": str(log_path) if log_path else "",
    }


def _tail(path: Path | None, limit: int = 220) -> str:
    if not path or not path.exists():
        return ""
    lines = path.read_text(errors="ignore").splitlines()
    return "\n".join(lines[-limit:])


def _bool_env(value: object) -> str:
    return "1" if bool(value) else "0"


def _settings_to_env(settings: dict) -> dict[str, str]:
    stages = settings.get("stages") or []
    if isinstance(stages, str):
        stages = [s.strip() for s in stages.split(",") if s.strip()]
    stages = [s for s in stages if s in STAGES]

    purchase_mode = str(settings.get("purchaseMode") or "preview").lower()
    if purchase_mode != "preview":
        raise RuntimeError("Dashboard runs are locked to PURCHASE_MODE=preview")

    google_phone_mode = str(settings.get("googlePhoneMode") or "manual").lower()
    if google_phone_mode != "manual":
        raise RuntimeError("Google phone verification from dashboard is manual only")

    gameplay_method = str(settings.get("gameplayMethod") or "auto").lower()
    if gameplay_method == "auto":
        gameplay_method = "fast"
    if gameplay_method == "off" and "gameplay" in stages:
        stages.remove("gameplay")

    env = {
        "DEVICE_FARM": str(settings.get("farm") or "local"),
        "LOCAL_DEVICE": str(settings.get("localDevice") or "auto"),
        "APPIUM_PORT": str(settings.get("appiumPort") or config.APPIUM_PORT),
        "GAME_PROFILE": str(settings.get("gameProfile") or ""),
        "GAME_NAME": str(settings.get("gameName") or ""),
        "GAME_PACKAGE": str(settings.get("gamePackage") or ""),
        "GAME_PLAYER_NAME_PREFIX": str(settings.get("playerPrefix") or "Player"),
        "GAME_APK_PATH": str(settings.get("apkPath") or ""),
        "INSTALL_AUTOPILOT_VIA": str(settings.get("installMethod") or "cv"),
        "GAME_AUTOPILOT_VIA": str(settings.get("tutorialMethod") or "cv"),
        "GAMEPLAY_AUTOPILOT_VIA": gameplay_method,
        "PURCHASE_AUTOPILOT_VIA": str(settings.get("purchaseMethod") or "cv"),
        "PURCHASE_MODE": "preview",
        "PURCHASE_PREVIEW_LEAVE_OPEN": _bool_env(settings.get("leavePurchaseOpen")),
        "GOOGLE_REGISTER_VIA": str(settings.get("googleRegisterVia") or "chrome"),
        "GOOGLE_PHONE_MODE": "manual",
        "TEST_RUN": _bool_env(settings.get("testRun")),
        "GOOGLE_EMAIL": str(settings.get("googleEmail") or ""),
        "GOOGLE_STOP_AT_PHONE_VERIFICATION": _bool_env(settings.get("stopAtPhone")),
        "FAST_GAMEPLAY_SECONDS": str(settings.get("fastGameplaySeconds") or "35"),
        "FAST_GAMEPLAY_FRAME_DELAY": str(settings.get("fastFrameDelay") or "0.05"),
        "MATCH3_GRID_ROWS": str(settings.get("match3Rows") or "9"),
        "MATCH3_GRID_COLS": str(settings.get("match3Cols") or "9"),
        "MATCH3_GRID_BOUNDS": str(settings.get("match3Bounds") or ""),
        "MATCH3_MAX_MOVES": str(settings.get("match3MaxMoves") or "12"),
        "CV_FAILURE_FALLBACK_TO_MANUAL": _bool_env(settings.get("cvFallbackManual", True)),
        "CV_MODELS": str(settings.get("cvModels") or ",".join(config.CV_MODELS)),
        "CV_COORDINATE_SCALE": str(settings.get("cvCoordinateScale") or config.CV_COORDINATE_SCALE),
        "CV_GAME_TUTORIAL_MAX_STEPS": str(settings.get("cvTutorialMaxSteps") or config.CV_GAME_TUTORIAL_MAX_STEPS),
        "CV_PURCHASE_PREVIEW_MAX_STEPS": str(settings.get("cvPurchaseMaxSteps") or config.CV_PURCHASE_PREVIEW_MAX_STEPS),
        "CV_INSTALL_GOAL_TEMPLATE": str(settings.get("cvInstallBasePrompt") or ""),
        "CV_TUTORIAL_GOAL_TEMPLATE": str(settings.get("cvTutorialBasePrompt") or ""),
        "CV_PURCHASE_GOAL_TEMPLATE": str(settings.get("cvPurchaseBasePrompt") or ""),
        "CV_INSTALL_GOAL_EXTRA": str(settings.get("cvInstallInstructions") or ""),
        "CV_TUTORIAL_GOAL_EXTRA": str(settings.get("cvTutorialInstructions") or ""),
        "CV_PURCHASE_GOAL_EXTRA": str(settings.get("cvPurchaseInstructions") or ""),
        "CV_EXTRA_BLOCKER_WORDS": str(settings.get("cvExtraBlockers") or ""),
        "RECORDED_INSTALL_PATH": str(settings.get("recordedInstallPath") or ""),
        "RECORDED_TUTORIAL_PATH": str(settings.get("recordedTutorialPath") or ""),
        "RECORDED_GAMEPLAY_PATH": str(settings.get("recordedGameplayPath") or ""),
        "MANUAL_CONTROL_TIMEOUT_SECONDS": str(settings.get("manualTimeout") or "600"),
    }
    secret_map = {
        "openrouterKey": "OPENROUTER_API_KEY",
        "genymotionToken": "GENYMOTION_API_TOKEN",
        "browserstackUsername": "BROWSERSTACK_USERNAME",
        "browserstackAccessKey": "BROWSERSTACK_ACCESS_KEY",
        "lambdatestUsername": "LT_USERNAME",
        "lambdatestAccessKey": "LT_ACCESS_KEY",
        "fivesimApiKey": "FIVESIM_API_KEY",
        "googlePhoneNumber": "GOOGLE_PHONE_NUMBER",
        "googleSmsCode": "GOOGLE_SMS_CODE",
        "googleSmsCodeFile": "GOOGLE_SMS_CODE_FILE",
    }
    for setting_key, env_key in secret_map.items():
        value = str(settings.get(setting_key) or "").strip()
        if value:
            env[env_key] = value
    if stages:
        env["RUN_STAGES"] = ",".join(stages)
    return env


def _default_settings() -> dict:
    profile = getattr(config, "SELECTED_GAME_PROFILE", None)
    return {
        "farm": getattr(config, "DEVICE_FARM", "local"),
        "localDevice": getattr(config, "LOCAL_DEVICE", "auto"),
        "appiumPort": getattr(config, "APPIUM_PORT", 4723),
        "gameProfile": getattr(config, "GAME_PROFILE_ID", "brawl-stars"),
        "gameName": getattr(config, "GAME_NAME", "Brawl Stars"),
        "gamePackage": getattr(config, "GAME_PACKAGE", "com.supercell.brawlstars"),
        "playerPrefix": getattr(config, "GAME_PLAYER_NAME_PREFIX", "Player"),
        "apkPath": getattr(config, "GAME_APK_PATH", ""),
        "installMethod": getattr(config, "INSTALL_AUTOPILOT_VIA", "cv"),
        "tutorialMethod": getattr(config, "GAME_AUTOPILOT_VIA", "cv"),
        "gameplayMethod": getattr(config, "GAMEPLAY_AUTOPILOT_VIA", "fast"),
        "purchaseMethod": getattr(config, "PURCHASE_AUTOPILOT_VIA", "cv"),
        "purchaseMode": "preview",
        "leavePurchaseOpen": getattr(config, "PURCHASE_PREVIEW_LEAVE_OPEN", False),
        "googleRegisterVia": getattr(config, "GOOGLE_REGISTER_VIA", "chrome"),
        "googlePhoneMode": "manual",
        "testRun": getattr(config, "TEST_RUN", False),
        "googleEmail": getattr(config, "GOOGLE_EMAIL", ""),
        "stopAtPhone": getattr(config, "GOOGLE_STOP_AT_PHONE_VERIFICATION", False),
        "fastGameplaySeconds": getattr(config, "FAST_GAMEPLAY_SECONDS", 35),
        "fastFrameDelay": getattr(config, "FAST_GAMEPLAY_FRAME_DELAY", 0.05),
        "match3Rows": getattr(config, "MATCH3_GRID_ROWS", 9),
        "match3Cols": getattr(config, "MATCH3_GRID_COLS", 9),
        "match3Bounds": getattr(config, "MATCH3_GRID_BOUNDS", ""),
        "match3MaxMoves": getattr(config, "MATCH3_MAX_MOVES", 12),
        "manualTimeout": getattr(config, "MANUAL_CONTROL_TIMEOUT_SECONDS", 600),
        "cvFallbackManual": True,
        "cvModels": ",".join(getattr(config, "CV_MODELS", [])),
        "cvCoordinateScale": getattr(config, "CV_COORDINATE_SCALE", "1.53"),
        "cvTutorialMaxSteps": getattr(config, "CV_GAME_TUTORIAL_MAX_STEPS", 120),
        "cvPurchaseMaxSteps": getattr(config, "CV_PURCHASE_PREVIEW_MAX_STEPS", 45),
        "cvInstallBasePrompt": getattr(config, "CV_INSTALL_GOAL_TEMPLATE", "") or INSTALL_GOAL_TEMPLATE,
        "cvTutorialBasePrompt": getattr(config, "CV_TUTORIAL_GOAL_TEMPLATE", "") or TUTORIAL_GOAL_TEMPLATE,
        "cvPurchaseBasePrompt": getattr(config, "CV_PURCHASE_GOAL_TEMPLATE", "") or PURCHASE_GOAL_TEMPLATE,
        "cvInstallInstructions": getattr(config, "CV_INSTALL_GOAL_EXTRA", ""),
        "cvTutorialInstructions": getattr(config, "CV_TUTORIAL_GOAL_EXTRA", ""),
        "cvPurchaseInstructions": getattr(config, "CV_PURCHASE_GOAL_EXTRA", ""),
        "cvExtraBlockers": ",".join(getattr(config, "CV_EXTRA_BLOCKER_WORDS", ())),
        "recordedInstallPath": getattr(config, "RECORDED_INSTALL_PATH", ""),
        "recordedTutorialPath": getattr(config, "RECORDED_TUTORIAL_PATH", ""),
        "recordedGameplayPath": getattr(config, "RECORDED_GAMEPLAY_PATH", ""),
        "stages": ["install", "tutorial", "gameplay", "purchase_preview"],
        "profileNotes": getattr(profile, "notes", ""),
    }


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "AutopilotDashboard/1.0"

    def do_GET(self) -> None:
        try:
            parsed = urlparse(self.path)
            if not self._request_authorized(parsed.path):
                if parsed.path == "/":
                    self._send_file(STATIC_DIR / "login.html")
                    return
                if parsed.path.startswith("/api/"):
                    self._send_auth_required()
                    return
            if parsed.path == "/":
                self._send_file(STATIC_DIR / "index.html")
            elif parsed.path.startswith("/static/"):
                self._send_static_file(parsed.path.removeprefix("/static/"))
            elif parsed.path == "/api/state":
                self._send_json(self._state_payload())
            elif parsed.path == "/api/log":
                self._send_json({"log": _tail(RUN_LOG_PATH)})
            elif parsed.path == "/api/recordings":
                self._send_json({"recordings": _recording_files()})
            elif parsed.path == "/api/profiles":
                self._send_json({"profiles": self._profiles_payload()})
            elif parsed.path == "/api/presets":
                self._send_json({"presets": _preset_files()})
            elif parsed.path == "/api/recordings/read":
                query = parse_qs(parsed.query)
                self._send_json(self._read_recording((query.get("path") or [""])[0]))
            elif parsed.path == "/api/files":
                self._send_json({"files": _project_files()})
            elif parsed.path == "/api/files/read":
                query = parse_qs(parsed.query)
                self._send_json(self._read_project_file((query.get("path") or [""])[0]))
            elif parsed.path == "/api/device/screenshot":
                query = parse_qs(parsed.query)
                serial = _select_serial((query.get("serial") or [""])[0])
                self._send_screenshot(serial)
            elif parsed.path == "/api/vision/inspector":
                query = parse_qs(parsed.query)
                serial_value = (query.get("serial") or [""])[0]
                serial = _select_serial(serial_value) if serial_value else ""
                self._send_json(vision_inspector_payload(serial=serial))
            elif parsed.path == "/api/vision/templates":
                self._send_json(list_template_library())
            elif parsed.path == "/api/builder/state":
                self._send_json(builder_state())
            else:
                self.send_error(404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def do_POST(self) -> None:
        try:
            parsed = urlparse(self.path)
            payload = self._read_json()
            if parsed.path == "/api/login":
                result, headers, status = self._login(payload)
                self._send_json(result, headers=headers, status=status)
            elif parsed.path == "/api/logout":
                self._send_json({"ok": True}, headers=[
                    ("Set-Cookie", f"{SESSION_COOKIE_NAME}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"),
                ])
            elif not self._request_authorized(parsed.path):
                self._send_auth_required()
            elif parsed.path == "/api/run":
                self._send_json(self._start_run(payload))
            elif parsed.path == "/api/stop":
                self._send_json(self._stop_run())
            elif parsed.path == "/api/check":
                self._send_json(self._check_project())
            elif parsed.path == "/api/preset":
                self._send_json(self._save_preset(payload))
            elif parsed.path == "/api/presets":
                self._send_json(self._save_named_preset(payload))
            elif parsed.path == "/api/presets/delete":
                self._send_json(self._delete_preset(payload))
            elif parsed.path == "/api/profiles":
                self._send_json(self._save_profile(payload))
            elif parsed.path == "/api/profiles/delete":
                self._send_json(self._delete_profile(payload))
            elif parsed.path == "/api/manual/continue":
                self._send_json(self._manual_continue())
            elif parsed.path == "/api/device/tap":
                self._send_json(self._device_tap(payload))
            elif parsed.path == "/api/device/swipe":
                self._send_json(self._device_swipe(payload))
            elif parsed.path == "/api/device/key":
                self._send_json(self._device_key(payload))
            elif parsed.path == "/api/device/text":
                self._send_json(self._device_text(payload))
            elif parsed.path == "/api/cv/plan":
                self._send_json(self._cv_plan(payload))
            elif parsed.path == "/api/cv/run":
                self._send_json(self._cv_run(payload))
            elif parsed.path == "/api/vision/templates":
                self._send_json(self._vision_save_template(payload))
            elif parsed.path == "/api/vision/roi":
                self._send_json(create_roi_from_payload(payload))
            elif parsed.path == "/api/vision/labels":
                self._send_json(export_label_from_payload(payload))
            elif parsed.path == "/api/builder/build":
                self._send_json(build_autopilot_from_payload(payload, adb_path=ADB_PATH))
            elif parsed.path == "/api/recordings":
                self._send_json(self._save_recording(payload))
            elif parsed.path == "/api/recordings/replay":
                self._send_json(self._replay_recording(payload))
            elif parsed.path == "/api/files/write":
                self._send_json(self._write_project_file(payload))
            else:
                self.send_error(404)
        except Exception as e:
            self._send_json({"error": str(e)}, status=500)

    def _request_authorized(self, path: str) -> bool:
        if not _dashboard_auth_enabled() or _is_public_path(path):
            return True
        if _session_authorized(self.headers.get("Cookie", "")):
            return True
        api_key = self.headers.get("X-Dashboard-Api-Key", "") or self.headers.get("Authorization", "")
        return _api_key_authorized(api_key)

    def _send_auth_required(self) -> None:
        self._send_json({"error": "authentication required"}, status=401)

    def _login(self, payload: dict) -> tuple[dict, list[tuple[str, str]], int]:
        username = str(payload.get("username") or "")
        password = str(payload.get("password") or "")
        if not _login_matches(username, password):
            return {"error": "Invalid dashboard username or password"}, [], 401
        token = _create_session(username)
        max_age = int(getattr(config, "DASHBOARD_SESSION_TTL_SECONDS", 86400) or 86400)
        headers = [
            (
                "Set-Cookie",
                f"{SESSION_COOKIE_NAME}={token}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax",
            )
        ]
        return {"ok": True, "username": username}, headers, 200

    def _state_payload(self) -> dict:
        profiles = self._profiles_payload()
        return {
            "profiles": profiles,
            "methods": {
                "farms": FARMS,
                "stages": STAGES,
                "googleRegister": GOOGLE_REGISTER_METHODS,
                "install": INSTALL_METHODS,
                "tutorial": TUTORIAL_METHODS,
                "gameplay": GAMEPLAY_METHODS,
                "purchase": PURCHASE_METHODS,
            },
            "settings": {**_default_settings(), **_load_preset()},
            "devices": _adb_devices(),
            "activeRun": _active_run(),
            "latestReport": _latest_report(),
            "recordings": _recording_files(),
            "readyPresets": _preset_files(),
            "vision": {
                "keyConfigured": _looks_like_secret(
                    os.getenv("OPENROUTER_API_KEY", "")
                    or getattr(config, "OPENROUTER_API_KEY", "")
                ),
                "models": getattr(config, "CV_MODELS", []),
            },
            "safety": {
                "purchaseMode": "preview",
                "googlePhoneMode": "manual",
                "notes": [
                    "Dashboard never starts a real purchase flow.",
                    "Google phone verification remains manual/user-controlled.",
                    "Manual mode gives you direct control; stop before Buy/Pay/Confirm.",
                ],
            },
            "auth": {
                "enabled": _dashboard_auth_enabled(),
                "username": _dashboard_username(),
                "mcpApiKeyConfigured": bool(_dashboard_mcp_api_key()),
            },
        }

    def _profiles_payload(self) -> list[dict]:
        profiles = []
        for profile in list_game_profiles():
            data = asdict(profile)
            data.update(profile_validation_summary(profile))
            path = _custom_profile_path(profile.id)
            if path.exists():
                data["source"] = "custom"
                data["editable"] = True
                data["path"] = _display_path(path)
            else:
                data["source"] = "builtin"
                data["editable"] = False
                data["path"] = ""
            data["settings"] = _profile_to_settings(data)
            profiles.append(data)
        return profiles

    def _start_run(self, payload: dict) -> dict:
        global RUN_PROCESS, RUN_LOG_PATH
        settings = payload.get("settings") or payload
        env_overrides = _settings_to_env(settings)
        env = os.environ.copy()
        env.update({k: v for k, v in env_overrides.items() if v is not None})
        RUNS_DIR.mkdir(parents=True, exist_ok=True)
        log_path = RUNS_DIR / f"run_{time.strftime('%Y%m%d_%H%M%S')}.log"
        with RUN_LOCK:
            if RUN_PROCESS and RUN_PROCESS.poll() is None:
                raise RuntimeError(f"Run already active: pid={RUN_PROCESS.pid}")
            log_file = log_path.open("w")
            RUN_PROCESS = subprocess.Popen(
                [sys.executable, "main.py"],
                cwd=ROOT,
                env=env,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                text=True,
            )
            log_file.close()
            RUN_LOG_PATH = log_path
        return {"started": True, "pid": RUN_PROCESS.pid, "logPath": str(log_path)}

    def _stop_run(self) -> dict:
        with RUN_LOCK:
            proc = RUN_PROCESS
        if not proc or proc.poll() is not None:
            return {"stopped": False, "message": "no active run"}
        proc.send_signal(signal.SIGINT)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        return {"stopped": True, "returncode": proc.poll()}

    def _check_project(self) -> dict:
        commands = [
            [
                sys.executable,
                "-m",
                "compileall",
                "-q",
                "core",
                "dashboard",
                "scenarios",
                "services",
                "tests",
                "bootstrap.py",
                "main.py",
                "config.py",
            ],
            [sys.executable, "-m", "pytest", "-q"],
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_dashboard_mcp_server.py",
                "tests/test_cv_prompt_templates.py",
                "tests/test_dashboard_cv_bridge.py",
                "tests/test_game_profiles.py",
                "--cov=dashboard.mcp_server",
                "--cov=core.cv_prompt_templates",
                "--cov=dashboard.cv_bridge",
                "--cov=core.game_profiles",
                "--cov-report=term-missing",
                "--cov-fail-under=100",
                "-q",
            ],
        ]
        outputs = []
        ok = True
        for command in commands:
            code, out, err = _run_command(command, timeout=90)
            outputs.append({"command": " ".join(command), "code": code, "stdout": out, "stderr": err})
            ok = ok and code == 0
        return {"ok": ok, "outputs": outputs}

    def _clean_preset_settings(self, payload: dict) -> dict:
        settings = dict(payload.get("settings") or payload)
        for secret in (
            "openrouterKey",
            "genymotionToken",
            "browserstackUsername",
            "browserstackAccessKey",
            "lambdatestUsername",
            "lambdatestAccessKey",
            "fivesimApiKey",
            "googlePhoneNumber",
            "googleSmsCode",
            "googleSmsCodeFile",
        ):
            settings.pop(secret, None)
        _settings_to_env(settings)
        return settings

    def _save_preset(self, payload: dict) -> dict:
        settings = self._clean_preset_settings(payload)
        PRESETS_DIR.mkdir(parents=True, exist_ok=True)
        LATEST_PRESET.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"saved": True, "path": str(LATEST_PRESET)}

    def _save_named_preset(self, payload: dict) -> dict:
        settings = self._clean_preset_settings(payload)
        name = str(payload.get("name") or settings.get("title") or settings.get("gameProfile") or "custom_preset")
        settings["title"] = str(payload.get("title") or settings.get("title") or name.replace("_", " "))
        settings["description"] = str(payload.get("description") or settings.get("description") or "")
        path = _preset_path(name)
        if not _inside_root(path, PRESETS_DIR.resolve()):
            raise RuntimeError("Preset path must stay inside dashboard/presets")
        path.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        LATEST_PRESET.write_text(json.dumps(settings, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "saved": True,
            "name": path.stem,
            "path": _display_path(path),
            "settings": settings,
        }

    def _delete_preset(self, payload: dict) -> dict:
        name = str(payload.get("name") or "").strip()
        path_value = str(payload.get("path") or "").strip()
        path = (ROOT / path_value).resolve() if path_value else _preset_path(name)
        if path.name == "latest.json":
            raise RuntimeError("latest.json cannot be deleted from the dashboard")
        if not _inside_root(path, PRESETS_DIR.resolve()):
            raise RuntimeError("Preset path must stay inside dashboard/presets")
        deleted = path.exists()
        if deleted:
            path.unlink()
        return {"deleted": deleted, "path": _display_path(path)}

    def _save_profile(self, payload: dict) -> dict:
        profile = game_profile_from_mapping(payload.get("profile") or payload)
        path = _custom_profile_path(profile.id)
        if not _inside_root(path, PROFILES_DIR.resolve()):
            raise RuntimeError("Profile path must stay inside dashboard/profiles")
        data = asdict(profile)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "saved": True,
            "profile": data,
            "path": _display_path(path),
            "settings": _profile_to_settings(data),
        }

    def _delete_profile(self, payload: dict) -> dict:
        profile_id = str(payload.get("id") or payload.get("profileId") or "").strip()
        if not profile_id:
            raise RuntimeError("Profile id is required")
        path = _custom_profile_path(profile_id)
        if not _inside_root(path, PROFILES_DIR.resolve()):
            raise RuntimeError("Profile path must stay inside dashboard/profiles")
        deleted = path.exists()
        if deleted:
            path.unlink()
        return {"deleted": deleted, "id": _safe_profile_id(profile_id), "path": _display_path(path)}

    def _save_recording(self, payload: dict) -> dict:
        name = _safe_recording_name(str(payload.get("name") or "manual_recording"))
        actions = payload.get("actions") or []
        if not isinstance(actions, list) or not actions:
            raise RuntimeError("Recording has no actions")
        RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
        path = RECORDINGS_DIR / f"{name}.json"
        data = {
            "name": name,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "actions": actions,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        return {"saved": True, "name": name, "path": str(path.relative_to(ROOT))}

    def _read_recording(self, path_value: str) -> dict:
        path = _resolve_recording_path(path_value=path_value)
        if not path.exists():
            raise RuntimeError(f"Recording not found: {path.relative_to(ROOT)}")
        content = path.read_text(encoding="utf-8")
        payload = json.loads(content)
        actions = payload.get("actions", []) if isinstance(payload, dict) else []
        return {
            "path": str(path.relative_to(ROOT)),
            "content": content,
            "actions": len(actions) if isinstance(actions, list) else 0,
        }

    def _replay_recording(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        path = _resolve_recording_path(
            path_value=str(payload.get("path") or ""),
            name=str(payload.get("name") or ""),
        )
        if not path.exists():
            raise RuntimeError(f"Recording not found: {path}")
        data = json.loads(path.read_text())
        actions = data.get("actions") or []
        for item in actions:
            self._replay_adb_action(serial, item)
            time.sleep(float(item.get("pause") or 0.35))
        return {"replayed": True, "actions": len(actions), "path": str(path)}

    def _replay_adb_action(self, serial: str, item: dict) -> None:
        action = str(item.get("action") or "").lower()
        if action == "tap":
            _run_command([
                ADB_PATH, "-s", serial, "shell", "input", "tap",
                str(int(item["x"])), str(int(item["y"])),
            ], timeout=8)
            return
        if action == "swipe":
            _run_command([
                ADB_PATH, "-s", serial, "shell", "input", "swipe",
                str(int(item["x1"])), str(int(item["y1"])),
                str(int(item["x2"])), str(int(item["y2"])),
                str(int(item.get("duration") or 350)),
            ], timeout=8)
            return
        if action == "key":
            codes = {"back": "4", "home": "3", "enter": "66", "menu": "82"}
            key = str(item.get("key") or "").lower()
            if key in codes:
                _run_command([ADB_PATH, "-s", serial, "shell", "input", "keyevent", codes[key]], timeout=8)
            return
        if action == "text":
            text = str(item.get("text") or "").replace(" ", "%s")
            _run_command([ADB_PATH, "-s", serial, "shell", "input", "text", text], timeout=8)

    def _read_project_file(self, path_value: str) -> dict:
        path, rel = _resolve_project_file(path_value)
        content = path.read_text(encoding="utf-8")
        return {"path": rel, "content": content, "size": len(content.encode("utf-8"))}

    def _write_project_file(self, payload: dict) -> dict:
        path, rel = _resolve_project_file(str(payload.get("path") or ""), must_exist=False)
        content = str(payload.get("content") or "")
        if len(content.encode("utf-8")) > MAX_EDIT_FILE_BYTES:
            raise RuntimeError("File content is too large for dashboard editing")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return {"saved": True, "path": rel, "size": len(content.encode("utf-8"))}

    def _manual_continue(self) -> dict:
        signal_path = ROOT / getattr(config, "MANUAL_CONTROL_SIGNAL_FILE", "dashboard/manual_continue.flag")
        signal_path.parent.mkdir(parents=True, exist_ok=True)
        signal_path.write_text(str(time.time()))
        return {"continued": True, "path": str(signal_path)}

    def _device_tap(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        x, y = int(payload["x"]), int(payload["y"])
        code, out, err = _run_command([ADB_PATH, "-s", serial, "shell", "input", "tap", str(x), str(y)], timeout=8)
        return {"ok": code == 0, "stdout": out, "stderr": err}

    def _device_swipe(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        args = [
            ADB_PATH,
            "-s",
            serial,
            "shell",
            "input",
            "swipe",
            str(int(payload["x1"])),
            str(int(payload["y1"])),
            str(int(payload["x2"])),
            str(int(payload["y2"])),
            str(int(payload.get("duration") or 350)),
        ]
        code, out, err = _run_command(args, timeout=8)
        return {"ok": code == 0, "stdout": out, "stderr": err}

    def _device_key(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        key = str(payload.get("key") or "back").lower()
        codes = {"back": "4", "home": "3", "enter": "66", "menu": "82"}
        if key not in codes:
            raise RuntimeError(f"Unsupported key: {key}")
        code, out, err = _run_command([ADB_PATH, "-s", serial, "shell", "input", "keyevent", codes[key]], timeout=8)
        return {"ok": code == 0, "stdout": out, "stderr": err}

    def _device_text(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        text = str(payload.get("text") or "")
        safe_text = text.replace(" ", "%s")
        code, out, err = _run_command([ADB_PATH, "-s", serial, "shell", "input", "text", safe_text], timeout=8)
        return {"ok": code == 0, "stdout": out, "stderr": err}

    def _cv_plan(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise RuntimeError("CV goal is required")
        return asyncio.run(plan_cv_action(
            serial=serial,
            goal=goal,
            values=payload_values(payload),
            recent_actions=payload_recent_actions(payload),
            api_key=payload_api_key(payload),
            models=payload_models(payload),
            adb_path=ADB_PATH,
        ))

    def _cv_run(self, payload: dict) -> dict:
        serial = _select_serial(str(payload.get("serial") or ""))
        goal = str(payload.get("goal") or "").strip()
        if not goal:
            raise RuntimeError("CV goal is required")
        return asyncio.run(run_cv_goal(
            serial=serial,
            goal=goal,
            values=payload_values(payload),
            max_steps=int(payload.get("maxSteps") or payload.get("max_steps") or 12),
            api_key=payload_api_key(payload),
            models=payload_models(payload),
            adb_path=ADB_PATH,
        ))

    def _vision_save_template(self, payload: dict) -> dict:
        screenshot = None
        if not (payload.get("screenshotBase64") or payload.get("imageBase64")):
            serial = _select_serial(str(payload.get("serial") or ""))
            screenshot = self._screenshot_bytes(serial)
        return save_template_from_payload(payload, screenshot_bytes=screenshot)

    def _screenshot_bytes(self, serial: str) -> bytes:
        proc = subprocess.run(
            [ADB_PATH, "-s", serial, "exec-out", "screencap", "-p"],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="ignore"))
        return proc.stdout

    def _send_screenshot(self, serial: str) -> None:
        screenshot = self._screenshot_bytes(serial)
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(screenshot)))
        self.end_headers()
        self.wfile.write(screenshot)

    def _send_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self.send_error(404)
            return
        mime = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_static_file(self, path_value: str) -> None:
        path = (STATIC_DIR / path_value).resolve()
        if not _inside_root(path, STATIC_DIR.resolve()):
            self.send_error(404)
            return
        self._send_file(path)

    def _send_json(
        self,
        payload: object,
        *,
        status: int = 200,
        headers: list[tuple[str, str]] | None = None,
    ) -> None:
        data = _json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for key, value in headers or []:
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_json(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw or "{}")

    def log_message(self, fmt: str, *args) -> None:
        sys.stderr.write("[dashboard] " + (fmt % args) + "\n")


def main() -> None:
    port = int(os.getenv("DASHBOARD_PORT", "8765"))
    host = os.getenv("DASHBOARD_HOST", "127.0.0.1").strip() or "127.0.0.1"
    _validate_dashboard_exposure(host)
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    print(f"Dashboard: http://{display_host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
