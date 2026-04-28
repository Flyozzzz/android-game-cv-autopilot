"""MCP bridge for the local Android autopilot dashboard.

The server speaks MCP over stdio and forwards tools to the dashboard HTTP API.
It intentionally keeps purchase runs locked to preview because the dashboard
API enforces the same guard in one place.
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from core.benchmark_matrix import run_benchmark_matrix


ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://127.0.0.1:8765").rstrip("/")
DASHBOARD_MCP_API_KEY = os.getenv("DASHBOARD_MCP_API_KEY", "change-me").strip()
AUTOSTART_DASHBOARD = os.getenv("MCP_AUTOSTART_DASHBOARD", "1").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
DASHBOARD_PROCESS: subprocess.Popen | None = None


def _schema(
    properties: dict[str, Any] | None = None,
    required: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }


TOOL_DEFS: list[dict[str, Any]] = [
    {
        "name": "dashboard_state",
        "description": "Read dashboard state: devices, profiles, methods, safe settings, active run, reports, and recordings.",
        "inputSchema": _schema(),
    },
    {
        "name": "start_safe_run",
        "description": "Start an automation run through the dashboard. Purchase mode is always forced to preview by the dashboard.",
        "inputSchema": _schema({
            "settings": {
                "type": "object",
                "description": "Dashboard settings override. If omitted, current dashboard settings are used.",
                "additionalProperties": True,
            }
        }),
    },
    {
        "name": "stop_run",
        "description": "Stop the active dashboard-started automation run.",
        "inputSchema": _schema(),
    },
    {
        "name": "run_checks",
        "description": "Run project compile checks and pytest through the dashboard.",
        "inputSchema": _schema(),
    },
    {
        "name": "tail_run_log",
        "description": "Read the current dashboard run log tail.",
        "inputSchema": _schema(),
    },
    {
        "name": "latest_report",
        "description": "Read the latest automation run report from dashboard state.",
        "inputSchema": _schema(),
    },
    {
        "name": "list_project_files",
        "description": "List dashboard-editable data files: presets, profiles, recordings, and prompt notes. Server code, secrets, logs, reports, caches, and virtualenvs are excluded.",
        "inputSchema": _schema({
            "contains": {"type": "string", "description": "Optional case-insensitive path filter."},
            "limit": {"type": "integer", "description": "Maximum files to return.", "minimum": 1, "maximum": 1000},
        }),
    },
    {
        "name": "read_project_file",
        "description": "Read one safe dashboard data file using the dashboard path guard.",
        "inputSchema": _schema({"path": {"type": "string"}}, ["path"]),
    },
    {
        "name": "write_project_file",
        "description": "Write one safe dashboard data file using the dashboard path guard.",
        "inputSchema": _schema({"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
    },
    {
        "name": "list_recordings",
        "description": "List saved manual action recordings.",
        "inputSchema": _schema(),
    },
    {
        "name": "read_recording",
        "description": "Read a saved recording JSON file.",
        "inputSchema": _schema({"path": {"type": "string"}}, ["path"]),
    },
    {
        "name": "save_recording",
        "description": "Save a manual action recording JSON file.",
        "inputSchema": _schema({
            "name": {"type": "string"},
            "actions": {"type": "array", "items": {"type": "object", "additionalProperties": True}},
        }, ["name", "actions"]),
    },
    {
        "name": "replay_recording",
        "description": "Replay a saved recording on the selected Android device via dashboard ADB controls.",
        "inputSchema": _schema({
            "path": {"type": "string"},
            "serial": {"type": "string", "description": "Optional ADB serial. Dashboard picks the first connected device if omitted."},
        }, ["path"]),
    },
    {
        "name": "list_game_profiles",
        "description": "List built-in and dashboard-created game profiles used by the automation constructor.",
        "inputSchema": _schema(),
    },
    {
        "name": "save_game_profile",
        "description": "Create or update a custom dashboard game profile JSON. Built-ins can be overridden by saving the same id.",
        "inputSchema": _schema({
            "profile": {"type": "object", "additionalProperties": True},
        }, ["profile"]),
    },
    {
        "name": "delete_game_profile",
        "description": "Delete a custom dashboard game profile override/file. Built-in defaults remain available.",
        "inputSchema": _schema({
            "id": {"type": "string"},
        }, ["id"]),
    },
    {
        "name": "list_presets",
        "description": "List named dashboard run presets.",
        "inputSchema": _schema(),
    },
    {
        "name": "save_preset",
        "description": "Create or update a named dashboard preset from full run settings. Secrets are stripped before saving.",
        "inputSchema": _schema({
            "name": {"type": "string"},
            "title": {"type": "string"},
            "description": {"type": "string"},
            "settings": {"type": "object", "additionalProperties": True},
        }, ["name", "settings"]),
    },
    {
        "name": "delete_preset",
        "description": "Delete a named dashboard preset JSON file.",
        "inputSchema": _schema({
            "name": {"type": "string"},
            "path": {"type": "string"},
        }),
    },
    {
        "name": "adb_devices",
        "description": "List connected Android devices seen by the dashboard.",
        "inputSchema": _schema(),
    },
    {
        "name": "device_screenshot",
        "description": "Capture the selected Android device screenshot. Returns MCP image content.",
        "inputSchema": _schema({
            "serial": {"type": "string", "description": "Optional ADB serial."}
        }),
    },
    {
        "name": "device_tap",
        "description": "Tap Android screen coordinates through dashboard ADB controls.",
        "inputSchema": _schema({
            "serial": {"type": "string"},
            "x": {"type": "integer"},
            "y": {"type": "integer"},
        }, ["x", "y"]),
    },
    {
        "name": "device_swipe",
        "description": "Swipe Android screen coordinates through dashboard ADB controls.",
        "inputSchema": _schema({
            "serial": {"type": "string"},
            "x1": {"type": "integer"},
            "y1": {"type": "integer"},
            "x2": {"type": "integer"},
            "y2": {"type": "integer"},
            "duration": {"type": "integer", "description": "Swipe duration in ms."},
        }, ["x1", "y1", "x2", "y2"]),
    },
    {
        "name": "device_key",
        "description": "Send a safe Android key event: back, home, enter, or menu.",
        "inputSchema": _schema({
            "serial": {"type": "string"},
            "key": {"type": "string", "enum": ["back", "home", "enter", "menu"]},
        }, ["key"]),
    },
    {
        "name": "device_text",
        "description": "Type text into the Android device through dashboard ADB controls.",
        "inputSchema": _schema({
            "serial": {"type": "string"},
            "text": {"type": "string"},
        }, ["text"]),
    },
    {
        "name": "cv_plan_next_action",
        "description": "Capture the Android screen and ask the dashboard CV engine for the next safe UI action. This only plans; it does not execute.",
        "inputSchema": _schema({
            "goal": {"type": "string", "description": "Task objective for the current Android screen."},
            "serial": {"type": "string", "description": "Optional ADB serial."},
            "values": {"type": "object", "description": "Optional named values the CV planner may type.", "additionalProperties": True},
            "recentActions": {"type": "array", "items": {"type": "string"}},
            "openrouterKey": {"type": "string", "description": "Optional one-shot OpenRouter key. It is not saved."},
            "models": {
                "description": "Optional CV model list as comma-separated string or array.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
        }, ["goal"]),
    },
    {
        "name": "cv_run_goal",
        "description": "Run the safe CV autopilot on the current Android screen. Risky purchase/payment actions stop the run instead of executing.",
        "inputSchema": _schema({
            "goal": {"type": "string", "description": "Task objective for the current Android screen."},
            "serial": {"type": "string", "description": "Optional ADB serial."},
            "values": {"type": "object", "description": "Optional named values the CV autopilot may type.", "additionalProperties": True},
            "maxSteps": {"type": "integer", "minimum": 1, "maximum": 60},
            "openrouterKey": {"type": "string", "description": "Optional one-shot OpenRouter key. It is not saved."},
            "models": {
                "description": "Optional CV model list as comma-separated string or array.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
        }, ["goal"]),
    },
    {
        "name": "vision_inspector_state",
        "description": "Read the latest Vision Inspector payload: screenshot URL, ROI, provider candidates, selected element, decision trace, and latency breakdown.",
        "inputSchema": _schema({
            "serial": {"type": "string", "description": "Optional ADB serial for the screenshot URL."},
        }),
    },
    {
        "name": "list_vision_templates",
        "description": "List saved template registry items and resolved PNG files from assets/templates.",
        "inputSchema": _schema(),
    },
    {
        "name": "save_vision_template",
        "description": "Save a template crop from the current inspector screenshot or a provided screenshotBase64 payload.",
        "inputSchema": _schema({
            "templateId": {"type": "string"},
            "namespace": {"type": "string"},
            "threshold": {"type": "number"},
            "roi": {"type": "string"},
            "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            "screenshotBase64": {"type": "string"},
            "tapOffset": {"type": "array", "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
            "negativeTemplates": {"type": "array", "items": {"type": "string"}},
        }, ["templateId", "bbox"]),
    },
    {
        "name": "create_vision_roi",
        "description": "Create or update a profile ROI zone from a normalized or pixel box.",
        "inputSchema": _schema({
            "profileId": {"type": "string"},
            "zoneName": {"type": "string"},
            "bbox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
            "width": {"type": "number"},
            "height": {"type": "number"},
            "normalizedBox": {"type": "array", "items": {"type": "number"}, "minItems": 4, "maxItems": 4},
        }, ["profileId", "zoneName"]),
    },
    {
        "name": "export_vision_label",
        "description": "Export the selected inspector candidate as a reusable label JSON artifact.",
        "inputSchema": _schema({
            "profileId": {"type": "string"},
            "labelId": {"type": "string"},
            "goal": {"type": "string"},
            "screenId": {"type": "string"},
            "roi": {"type": "object", "additionalProperties": True},
            "candidate": {"type": "object", "additionalProperties": True},
        }, ["profileId", "labelId", "candidate"]),
    },
    {
        "name": "autopilot_builder_state",
        "description": "Read Autopilot Builder state: saved bundles, configured vision models, and output root.",
        "inputSchema": _schema(),
    },
    {
        "name": "build_autopilot",
        "description": "Run the LLM Autopilot Builder from a goal prompt and optional replay/live validation settings.",
        "inputSchema": _schema({
            "prompt": {"type": "string"},
            "mode": {"type": "string", "enum": ["create", "improve", "repair", "validate", "shadow"]},
            "serial": {"type": "string"},
            "package": {"type": "string"},
            "models": {
                "description": "Optional vision model list as comma-separated string or array.",
                "oneOf": [
                    {"type": "string"},
                    {"type": "array", "items": {"type": "string"}},
                ],
            },
            "openrouterKey": {"type": "string", "description": "Optional one-shot OpenRouter key. It is not saved."},
            "framePaths": {"type": "array", "items": {"type": "string"}},
            "launchApp": {"type": "boolean"},
            "liveValidation": {"type": "boolean"},
        }, ["prompt"]),
    },
    {
        "name": "run_benchmark_matrix",
        "description": "Run profile/device benchmark matrix validation and save a JSON report under reports/benchmark_matrix.",
        "inputSchema": _schema({
            "serial": {"type": "string", "description": "Required ADB serial."},
            "profiles": {"type": "array", "items": {"type": "string"}, "description": "Optional profile ids/packages. Defaults to all profiles."},
            "runs": {"type": "integer", "minimum": 1, "maximum": 50, "description": "Runs per profile; use 20 for release evidence."},
            "noExplore": {"type": "boolean", "description": "Only launch/capture; skip safe exploration gestures."},
        }, ["serial"]),
    },
    {
        "name": "manual_continue",
        "description": "Release a manual checkpoint waiting in the automation run.",
        "inputSchema": _schema(),
    },
]


def _log(message: str) -> None:
    print(f"[dashboard-mcp] {message}", file=sys.stderr, flush=True)


def _ensure_dashboard() -> None:
    try:
        _http_json("GET", "/api/state", ensure=False)
        return
    except Exception:
        if not AUTOSTART_DASHBOARD:
            raise

    global DASHBOARD_PROCESS
    if DASHBOARD_PROCESS and DASHBOARD_PROCESS.poll() is None:
        return

    log_dir = ROOT / "dashboard" / "runs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "mcp_dashboard.log"
    log_file = log_path.open("a")
    DASHBOARD_PROCESS = subprocess.Popen(
        [sys.executable, "-m", "dashboard.server"],
        cwd=ROOT,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    _log(f"started dashboard pid={DASHBOARD_PROCESS.pid} log={log_path}")
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            _http_json("GET", "/api/state", ensure=False)
            return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Dashboard did not become ready")


def _http_json(method: str, path: str, payload: Any | None = None, *, ensure: bool = True) -> Any:
    if ensure:
        _ensure_dashboard()
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if DASHBOARD_MCP_API_KEY:
        headers["X-Dashboard-Api-Key"] = DASHBOARD_MCP_API_KEY
    request = Request(
        DASHBOARD_URL + path,
        data=data,
        method=method,
        headers=headers,
    )
    with urlopen(request, timeout=120) as response:
        raw = response.read()
        content_type = response.headers.get("Content-Type", "")
    if "application/json" not in content_type:
        return raw.decode("utf-8", errors="replace")
    result = json.loads(raw.decode("utf-8"))
    if isinstance(result, dict) and result.get("error"):
        raise RuntimeError(str(result["error"]))
    return result


def _http_bytes(path: str) -> bytes:
    _ensure_dashboard()
    headers = {}
    if DASHBOARD_MCP_API_KEY:
        headers["X-Dashboard-Api-Key"] = DASHBOARD_MCP_API_KEY
    request = Request(DASHBOARD_URL + path, headers=headers)
    with urlopen(request, timeout=60) as response:
        return response.read()


def _json_text(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(value, ensure_ascii=False, indent=2),
            }
        ]
    }


def call_tool(name: str, args: dict[str, Any] | None = None) -> dict[str, Any]:
    args = args or {}
    if name == "dashboard_state":
        return _json_text(_http_json("GET", "/api/state"))
    if name == "start_safe_run":
        settings = args.get("settings")
        if settings is None:
            settings = _http_json("GET", "/api/state").get("settings", {})
        return _json_text(_http_json("POST", "/api/run", {"settings": settings}))
    if name == "stop_run":
        return _json_text(_http_json("POST", "/api/stop", {}))
    if name == "run_checks":
        return _json_text(_http_json("POST", "/api/check", {}))
    if name == "tail_run_log":
        return _json_text(_http_json("GET", "/api/log"))
    if name == "latest_report":
        return _json_text(_http_json("GET", "/api/state").get("latestReport", {}))
    if name == "list_project_files":
        files = _http_json("GET", "/api/files").get("files", [])
        contains = str(args.get("contains") or "").lower()
        if contains:
            files = [item for item in files if contains in str(item.get("path", "")).lower()]
        limit = int(args.get("limit") or 300)
        return _json_text({"files": files[:limit], "total": len(files)})
    if name == "read_project_file":
        query = urlencode({"path": str(args["path"])})
        return _json_text(_http_json("GET", f"/api/files/read?{query}"))
    if name == "write_project_file":
        return _json_text(_http_json("POST", "/api/files/write", {
            "path": str(args["path"]),
            "content": str(args["content"]),
        }))
    if name == "list_recordings":
        return _json_text(_http_json("GET", "/api/recordings"))
    if name == "read_recording":
        query = urlencode({"path": str(args["path"])})
        return _json_text(_http_json("GET", f"/api/recordings/read?{query}"))
    if name == "save_recording":
        return _json_text(_http_json("POST", "/api/recordings", {
            "name": str(args["name"]),
            "actions": args["actions"],
        }))
    if name == "replay_recording":
        return _json_text(_http_json("POST", "/api/recordings/replay", {
            "path": str(args["path"]),
            "serial": str(args.get("serial") or ""),
        }))
    if name == "list_game_profiles":
        return _json_text(_http_json("GET", "/api/profiles"))
    if name == "save_game_profile":
        return _json_text(_http_json("POST", "/api/profiles", {"profile": args["profile"]}))
    if name == "delete_game_profile":
        return _json_text(_http_json("POST", "/api/profiles/delete", {"id": str(args["id"])}))
    if name == "list_presets":
        return _json_text(_http_json("GET", "/api/presets"))
    if name == "save_preset":
        return _json_text(_http_json("POST", "/api/presets", {
            "name": str(args["name"]),
            "title": str(args.get("title") or ""),
            "description": str(args.get("description") or ""),
            "settings": args["settings"],
        }))
    if name == "delete_preset":
        return _json_text(_http_json("POST", "/api/presets/delete", {
            "name": str(args.get("name") or ""),
            "path": str(args.get("path") or ""),
        }))
    if name == "adb_devices":
        return _json_text({"devices": _http_json("GET", "/api/state").get("devices", [])})
    if name == "device_screenshot":
        serial = str(args.get("serial") or "")
        query = "?" + urlencode({"serial": serial}) if serial else ""
        data = _http_bytes(f"/api/device/screenshot{query}")
        return {
            "content": [
                {"type": "text", "text": f"Android screenshot captured ({len(data)} bytes)."},
                {
                    "type": "image",
                    "data": base64.b64encode(data).decode("ascii"),
                    "mimeType": "image/png",
                },
            ]
        }
    if name == "device_tap":
        return _json_text(_http_json("POST", "/api/device/tap", {
            "serial": str(args.get("serial") or ""),
            "x": int(args["x"]),
            "y": int(args["y"]),
        }))
    if name == "device_swipe":
        return _json_text(_http_json("POST", "/api/device/swipe", {
            "serial": str(args.get("serial") or ""),
            "x1": int(args["x1"]),
            "y1": int(args["y1"]),
            "x2": int(args["x2"]),
            "y2": int(args["y2"]),
            "duration": int(args.get("duration") or 350),
        }))
    if name == "device_key":
        return _json_text(_http_json("POST", "/api/device/key", {
            "serial": str(args.get("serial") or ""),
            "key": str(args["key"]),
        }))
    if name == "device_text":
        return _json_text(_http_json("POST", "/api/device/text", {
            "serial": str(args.get("serial") or ""),
            "text": str(args["text"]),
        }))
    if name == "cv_plan_next_action":
        return _json_text(_http_json("POST", "/api/cv/plan", args))
    if name == "cv_run_goal":
        return _json_text(_http_json("POST", "/api/cv/run", args))
    if name == "vision_inspector_state":
        query = urlencode({"serial": str(args.get("serial") or "")})
        return _json_text(_http_json("GET", f"/api/vision/inspector?{query}"))
    if name == "list_vision_templates":
        return _json_text(_http_json("GET", "/api/vision/templates"))
    if name == "save_vision_template":
        return _json_text(_http_json("POST", "/api/vision/templates", args))
    if name == "create_vision_roi":
        return _json_text(_http_json("POST", "/api/vision/roi", args))
    if name == "export_vision_label":
        return _json_text(_http_json("POST", "/api/vision/labels", args))
    if name == "autopilot_builder_state":
        return _json_text(_http_json("GET", "/api/builder/state"))
    if name == "build_autopilot":
        return _json_text(_http_json("POST", "/api/builder/build", args))
    if name == "run_benchmark_matrix":
        matrix = run_benchmark_matrix(
            serial=str(args["serial"]),
            profile_ids=[str(item) for item in args.get("profiles") or []],
            runs=max(1, min(50, int(args.get("runs") or 20))),
            explore=not bool(args.get("noExplore", False)),
        )
        return _json_text(matrix)
    if name == "manual_continue":
        return _json_text(_http_json("POST", "/api/manual/continue", {}))
    raise RuntimeError(f"Unknown tool: {name}")


def _resource_list() -> list[dict[str, str]]:
    return [
        {
            "uri": "dashboard://state",
            "name": "Dashboard state",
            "description": "Current dashboard state as JSON.",
            "mimeType": "application/json",
        },
        {
            "uri": "dashboard://log",
            "name": "Run log tail",
            "description": "Tail of the current dashboard run log.",
            "mimeType": "application/json",
        },
        {
            "uri": "dashboard://latest-report",
            "name": "Latest run report",
            "description": "Latest automation report.",
            "mimeType": "application/json",
        },
    ]


def _resource_read(uri: str) -> dict[str, Any]:
    if uri == "dashboard://state":
        payload = _http_json("GET", "/api/state")
    elif uri == "dashboard://log":
        payload = _http_json("GET", "/api/log")
    elif uri == "dashboard://latest-report":
        payload = _http_json("GET", "/api/state").get("latestReport", {})
    else:
        raise RuntimeError(f"Unknown resource: {uri}")
    return {
        "contents": [
            {
                "uri": uri,
                "mimeType": "application/json",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ]
    }


def _prompt_list() -> list[dict[str, Any]]:
    return [
        {
            "name": "safe_android_automation_operator",
            "description": "Operate this Android dashboard safely through MCP tools.",
            "arguments": [],
        }
    ]


def _prompt_get(name: str) -> dict[str, Any]:
    if name != "safe_android_automation_operator":
        raise RuntimeError(f"Unknown prompt: {name}")
    return {
        "description": "Safe operator instructions for the Android game autopilot dashboard.",
        "messages": [
            {
                "role": "user",
                "content": {
                    "type": "text",
                    "text": (
                        "Use the Android Autopilot dashboard MCP tools to inspect state, "
                        "edit prompts/settings/files, run checks, control the connected "
                        "device, ask CV for the next safe UI action, record/replay safe "
                        "action paths, inspect Vision ROI/candidates/templates, create "
                        "game profiles and presets, build autopilot bundles, and start safe "
                        "runs. Never attempt real purchases: dashboard runs are locked to "
                        "PURCHASE_MODE=preview and Google phone verification is manual."
                    ),
                },
            }
        ],
    }


class MCPServer:
    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = str(message.get("method") or "")
        request_id = message.get("id")
        params = message.get("params") or {}
        try:
            if method == "initialize":
                result = {
                    "protocolVersion": params.get("protocolVersion") or "2024-11-05",
                    "capabilities": {
                        "tools": {},
                        "resources": {},
                        "prompts": {},
                    },
                    "serverInfo": {
                        "name": "android-autopilot-dashboard",
                        "version": "1.0.0",
                    },
                }
            elif method == "notifications/initialized":
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOL_DEFS}
            elif method == "tools/call":
                result = call_tool(str(params.get("name") or ""), params.get("arguments") or {})
            elif method == "resources/list":
                result = {"resources": _resource_list()}
            elif method == "resources/read":
                result = _resource_read(str(params.get("uri") or ""))
            elif method == "prompts/list":
                result = {"prompts": _prompt_list()}
            elif method == "prompts/get":
                result = _prompt_get(str(params.get("name") or ""))
            else:
                raise RuntimeError(f"Unsupported MCP method: {method}")
            if request_id is None:
                return None
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except Exception as exc:
            if request_id is None:
                _log(str(exc))
                return None
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32000, "message": str(exc)},
            }


def _read_message(stream) -> dict[str, Any] | None:
    first = stream.readline()
    if not first:
        return None
    if first.startswith(b"{"):
        return json.loads(first.decode("utf-8"))

    headers: dict[str, str] = {}
    line = first
    while line and line not in (b"\r\n", b"\n"):
        key, _, value = line.decode("ascii", errors="replace").partition(":")
        headers[key.strip().lower()] = value.strip()
        line = stream.readline()
    length = int(headers.get("content-length") or "0")
    if length <= 0:
        return None
    body = stream.read(length)
    return json.loads(body.decode("utf-8"))


def _write_message(stream, message: dict[str, Any]) -> None:
    body = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    stream.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    stream.flush()


def main() -> None:  # pragma: no cover - exercised by MCP clients over stdio.
    server = MCPServer()
    while True:
        message = _read_message(sys.stdin.buffer)
        if message is None:
            return
        response = server.handle(message)
        if response is not None:
            _write_message(sys.stdout.buffer, response)


if __name__ == "__main__":  # pragma: no cover
    main()
