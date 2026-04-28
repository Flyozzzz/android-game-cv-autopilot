import io
import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from dashboard import mcp_server


def _content_json(result):
    return json.loads(result["content"][0]["text"])


def test_mcp_initialize_and_lists_tools():
    server = mcp_server.MCPServer()

    init = server.handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-06-18"},
    })
    tools = server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    notification = server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"})

    assert init["result"]["protocolVersion"] == "2025-06-18"
    assert init["result"]["serverInfo"]["name"] == "android-autopilot-dashboard"
    assert {tool["name"] for tool in tools["result"]["tools"]} >= {
        "dashboard_state",
        "start_safe_run",
        "run_checks",
        "write_project_file",
        "device_screenshot",
        "cv_plan_next_action",
        "vision_inspector_state",
        "build_autopilot",
        "run_benchmark_matrix",
        "save_game_profile",
        "save_preset",
    }
    assert notification is None


def test_mcp_unknown_tool_returns_json_rpc_error():
    response = mcp_server.MCPServer().handle({
        "jsonrpc": "2.0",
        "id": 9,
        "method": "tools/call",
        "params": {"name": "missing_tool", "arguments": {}},
    })

    assert response["error"]["code"] == -32000
    assert "Unknown tool" in response["error"]["message"]


def test_mcp_prompts_and_resources(monkeypatch):
    def fake_http(method, path, payload=None, ensure=True):
        if path == "/api/log":
            return {"log": "tail"}
        return {
            "settings": {"gameName": "Game"},
            "latestReport": {"final_status": "success"},
        }

    monkeypatch.setattr(mcp_server, "_http_json", fake_http)
    server = mcp_server.MCPServer()

    prompts = server.handle({"jsonrpc": "2.0", "id": 1, "method": "prompts/list"})
    prompt = server.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "prompts/get",
        "params": {"name": "safe_android_automation_operator"},
    })
    resources = server.handle({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    state = server.handle({
        "jsonrpc": "2.0",
        "id": 4,
        "method": "resources/read",
        "params": {"uri": "dashboard://state"},
    })
    log = server.handle({
        "jsonrpc": "2.0",
        "id": 5,
        "method": "resources/read",
        "params": {"uri": "dashboard://log"},
    })
    latest = server.handle({
        "jsonrpc": "2.0",
        "id": 6,
        "method": "resources/read",
        "params": {"uri": "dashboard://latest-report"},
    })

    assert prompts["result"]["prompts"][0]["name"] == "safe_android_automation_operator"
    assert "Never attempt real purchases" in prompt["result"]["messages"][0]["content"]["text"]
    assert {item["uri"] for item in resources["result"]["resources"]} >= {"dashboard://state"}
    assert "Game" in state["result"]["contents"][0]["text"]
    assert "tail" in log["result"]["contents"][0]["text"]
    assert "success" in latest["result"]["contents"][0]["text"]


def test_mcp_tool_calls_route_to_dashboard_http(monkeypatch):
    calls = []

    def fake_http_json(method, path, payload=None, ensure=True):
        calls.append((method, path, payload))
        if path == "/api/state":
            return {
                "settings": {"gameName": "Current Game"},
                "devices": [{"serial": "emu", "state": "device"}],
                "latestReport": {"final_status": "success"},
            }
        if path == "/api/files":
            return {"files": [
                {"path": "config.py", "size": 100},
                {"path": "dashboard/server.py", "size": 200},
            ]}
        if path.startswith("/api/files/read"):
            return {"path": "config.py", "content": "x", "size": 1}
        if path == "/api/files/write":
            return {"saved": True, "path": payload["path"], "size": len(payload["content"])}
        if path == "/api/recordings":
            if method == "GET":
                return {"recordings": [{"path": "dashboard/recordings/a.json", "actions": "2"}]}
            return {"saved": True, "path": "dashboard/recordings/a.json"}
        if path == "/api/profiles":
            if method == "GET":
                return {"profiles": [{"id": "custom-game", "name": "Custom Game"}]}
            return {"saved": True, "profile": payload["profile"]}
        if path == "/api/profiles/delete":
            return {"deleted": True, "id": payload["id"]}
        if path == "/api/presets":
            if method == "GET":
                return {"presets": [{"name": "preset", "path": "dashboard/presets/preset.json"}]}
            return {"saved": True, "path": "dashboard/presets/preset.json"}
        if path == "/api/presets/delete":
            return {"deleted": True, "path": payload.get("path") or payload.get("name")}
        if path.startswith("/api/recordings/read"):
            return {"path": "dashboard/recordings/a.json", "content": "{}", "actions": 0}
        if path == "/api/run":
            return {"started": True, "pid": 123}
        if path == "/api/stop":
            return {"stopped": True}
        if path == "/api/check":
            return {"ok": True}
        if path == "/api/log":
            return {"log": "tail"}
        if path.startswith("/api/vision/inspector"):
            return {"frame": {"source": "adb"}, "overlay": {"candidates": []}}
        if path == "/api/vision/templates" and method == "GET":
            return {"templates": [{"id": "play_button", "namespace": "common"}], "total": 1}
        if path == "/api/builder/state":
            return {"bundles": [{"id": "demo"}], "models": ["xiaomi/mimo-v2.5"]}
        if path in {
            "/api/recordings/replay",
            "/api/device/tap",
            "/api/device/swipe",
            "/api/device/key",
            "/api/device/text",
            "/api/cv/plan",
            "/api/cv/run",
            "/api/vision/templates",
            "/api/vision/roi",
            "/api/vision/labels",
            "/api/builder/build",
            "/api/manual/continue",
        }:
            return {"ok": True, "path": path}
        raise AssertionError(path)

    monkeypatch.setattr(mcp_server, "_http_json", fake_http_json)

    assert _content_json(mcp_server.call_tool("dashboard_state"))["settings"]["gameName"] == "Current Game"
    assert _content_json(mcp_server.call_tool("start_safe_run"))["pid"] == 123
    assert _content_json(mcp_server.call_tool("start_safe_run", {"settings": {"gameName": "X"}}))["started"]
    assert _content_json(mcp_server.call_tool("stop_run"))["stopped"]
    assert _content_json(mcp_server.call_tool("run_checks"))["ok"]
    assert _content_json(mcp_server.call_tool("tail_run_log"))["log"] == "tail"
    assert _content_json(mcp_server.call_tool("latest_report"))["final_status"] == "success"
    assert _content_json(mcp_server.call_tool("list_project_files", {"contains": "dash", "limit": 1}))["total"] == 1
    assert _content_json(mcp_server.call_tool("read_project_file", {"path": "config.py"}))["content"] == "x"
    assert _content_json(mcp_server.call_tool("write_project_file", {"path": "a.py", "content": "123"}))["size"] == 3
    assert _content_json(mcp_server.call_tool("list_recordings"))["recordings"]
    assert _content_json(mcp_server.call_tool("read_recording", {"path": "dashboard/recordings/a.json"}))["actions"] == 0
    assert _content_json(mcp_server.call_tool("save_recording", {"name": "a", "actions": [{"action": "tap"}]}))["saved"]
    assert _content_json(mcp_server.call_tool("replay_recording", {"path": "dashboard/recordings/a.json"}))["ok"]
    assert _content_json(mcp_server.call_tool("list_game_profiles"))["profiles"][0]["id"] == "custom-game"
    assert _content_json(mcp_server.call_tool("save_game_profile", {"profile": {"id": "custom-game", "name": "Custom Game"}}))["saved"]
    assert _content_json(mcp_server.call_tool("delete_game_profile", {"id": "custom-game"}))["deleted"]
    assert _content_json(mcp_server.call_tool("list_presets"))["presets"][0]["name"] == "preset"
    assert _content_json(mcp_server.call_tool("save_preset", {"name": "preset", "settings": {"gameName": "Game"}}))["saved"]
    assert _content_json(mcp_server.call_tool("delete_preset", {"path": "dashboard/presets/preset.json"}))["deleted"]
    assert _content_json(mcp_server.call_tool("adb_devices"))["devices"][0]["serial"] == "emu"
    assert _content_json(mcp_server.call_tool("device_tap", {"x": 1, "y": 2}))["ok"]
    assert _content_json(mcp_server.call_tool("device_swipe", {"x1": 1, "y1": 2, "x2": 3, "y2": 4}))["ok"]
    assert _content_json(mcp_server.call_tool("device_key", {"key": "back"}))["ok"]
    assert _content_json(mcp_server.call_tool("device_text", {"text": "hello"}))["ok"]
    assert _content_json(mcp_server.call_tool("cv_plan_next_action", {"goal": "continue"}))["ok"]
    assert _content_json(mcp_server.call_tool("cv_run_goal", {"goal": "continue", "maxSteps": 2}))["ok"]
    assert _content_json(mcp_server.call_tool("vision_inspector_state"))["frame"]["source"] == "adb"
    assert _content_json(mcp_server.call_tool("list_vision_templates"))["total"] == 1
    assert _content_json(mcp_server.call_tool("save_vision_template", {"templateId": "play", "bbox": [1, 2, 3, 4]}))["ok"]
    assert _content_json(mcp_server.call_tool("create_vision_roi", {"profileId": "demo", "zoneName": "bottom_buttons"}))["ok"]
    assert _content_json(mcp_server.call_tool("export_vision_label", {"profileId": "demo", "labelId": "play", "candidate": {"name": "play"}}))["ok"]
    assert _content_json(mcp_server.call_tool("autopilot_builder_state"))["bundles"][0]["id"] == "demo"
    assert _content_json(mcp_server.call_tool("build_autopilot", {"prompt": "build demo"}))["ok"]
    assert _content_json(mcp_server.call_tool("manual_continue"))["ok"]
    assert calls


def test_mcp_can_run_benchmark_matrix(monkeypatch):
    def fake_matrix(**kwargs):
        return {
            "device": {"serial": kwargs["serial"]},
            "runs_per_profile": kwargs["runs"],
            "summary": {"profiles": 1, "passed_profiles": 1, "failed_profiles": 0},
            "rows": [{"profile_id": kwargs["profile_ids"][0], "result": "passed"}],
        }

    monkeypatch.setattr(mcp_server, "run_benchmark_matrix", fake_matrix)

    result = _content_json(
        mcp_server.call_tool(
            "run_benchmark_matrix",
            {"serial": "emu", "profiles": ["subway-surfers"], "runs": 2, "noExplore": True},
        )
    )

    assert result["device"]["serial"] == "emu"
    assert result["runs_per_profile"] == 2
    assert result["rows"][0]["profile_id"] == "subway-surfers"


def test_mcp_device_screenshot_returns_image(monkeypatch):
    monkeypatch.setattr(mcp_server, "_http_bytes", lambda path: b"\x89PNG\r\n")

    result = mcp_server.call_tool("device_screenshot", {"serial": "emu"})

    assert result["content"][0]["type"] == "text"
    assert result["content"][1]["type"] == "image"
    assert result["content"][1]["mimeType"] == "image/png"


def test_mcp_http_json_handles_json_text_and_dashboard_errors(monkeypatch):
    class FakeResponse:
        def __init__(self, body, content_type):
            self.body = body
            self.headers = {"Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return self.body

    monkeypatch.setattr(mcp_server, "_ensure_dashboard", lambda: None)
    monkeypatch.setattr(
        mcp_server,
        "urlopen",
        lambda request, timeout=120: FakeResponse(b'{"ok": true}', "application/json"),
    )
    assert mcp_server._http_json("GET", "/x") == {"ok": True}

    monkeypatch.setattr(
        mcp_server,
        "urlopen",
        lambda request, timeout=120: FakeResponse(b"plain", "text/plain"),
    )
    assert mcp_server._http_json("GET", "/x") == "plain"

    monkeypatch.setattr(
        mcp_server,
        "urlopen",
        lambda request, timeout=120: FakeResponse(b'{"error": "bad"}', "application/json"),
    )
    with pytest.raises(RuntimeError, match="bad"):
        mcp_server._http_json("GET", "/x")


def test_mcp_http_bytes_reads_response(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"bytes"

    monkeypatch.setattr(mcp_server, "_ensure_dashboard", lambda: None)
    monkeypatch.setattr(mcp_server, "urlopen", lambda url, timeout=60: FakeResponse())

    assert mcp_server._http_bytes("/shot") == b"bytes"


def test_mcp_ensure_dashboard_modes(monkeypatch):
    calls = {"http": 0, "popen": 0, "sleep": 0}

    def fail_then_succeed(method, path, payload=None, ensure=True):
        calls["http"] += 1
        if calls["http"] == 1:
            raise URLError("offline")
        return {"ok": True}

    class FakeProcess:
        pid = 42

        def poll(self):
            return 0

    monkeypatch.setattr(mcp_server, "AUTOSTART_DASHBOARD", True)
    monkeypatch.setattr(mcp_server, "DASHBOARD_PROCESS", None)
    monkeypatch.setattr(mcp_server, "_http_json", fail_then_succeed)
    monkeypatch.setattr(mcp_server.subprocess, "Popen", lambda *a, **k: calls.__setitem__("popen", calls["popen"] + 1) or FakeProcess())
    monkeypatch.setattr(mcp_server.time, "monotonic", lambda: 1 if calls["sleep"] < 1 else 20)
    monkeypatch.setattr(mcp_server.time, "sleep", lambda seconds: calls.__setitem__("sleep", calls["sleep"] + 1))

    mcp_server._ensure_dashboard()

    assert calls["popen"] == 1


def test_mcp_ensure_dashboard_existing_child_and_autostart_disabled(monkeypatch):
    class RunningProcess:
        def poll(self):
            return None

    monkeypatch.setattr(mcp_server, "_http_json", lambda *a, **k: (_ for _ in ()).throw(URLError("offline")))
    monkeypatch.setattr(mcp_server, "AUTOSTART_DASHBOARD", True)
    monkeypatch.setattr(mcp_server, "DASHBOARD_PROCESS", RunningProcess())
    assert mcp_server._ensure_dashboard() is None

    monkeypatch.setattr(mcp_server, "AUTOSTART_DASHBOARD", False)
    monkeypatch.setattr(mcp_server, "DASHBOARD_PROCESS", None)
    with pytest.raises(URLError):
        mcp_server._ensure_dashboard()


def test_mcp_ensure_dashboard_fast_success_and_timeout(monkeypatch):
    monkeypatch.setattr(mcp_server, "_http_json", lambda *a, **k: {"ok": True})
    assert mcp_server._ensure_dashboard() is None

    class FakeProcess:
        pid = 43

        def poll(self):
            return 1

    ticks = iter([0, 0, 20])
    monkeypatch.setattr(mcp_server, "AUTOSTART_DASHBOARD", True)
    monkeypatch.setattr(mcp_server, "DASHBOARD_PROCESS", None)
    monkeypatch.setattr(mcp_server, "_http_json", lambda *a, **k: (_ for _ in ()).throw(URLError("offline")))
    monkeypatch.setattr(mcp_server.subprocess, "Popen", lambda *a, **k: FakeProcess())
    monkeypatch.setattr(mcp_server.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(mcp_server.time, "sleep", lambda seconds: None)

    with pytest.raises(RuntimeError, match="Dashboard did not become ready"):
        mcp_server._ensure_dashboard()


def test_mcp_message_framing_round_trip():
    message = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    stream = io.BytesIO()

    mcp_server._write_message(stream, message)
    stream.seek(0)

    assert mcp_server._read_message(stream) == message


def test_mcp_read_message_accepts_newline_json():
    stream = io.BytesIO(b'{"jsonrpc":"2.0","id":1,"method":"ping"}\n')

    assert mcp_server._read_message(stream)["method"] == "ping"


def test_mcp_read_message_empty_and_zero_length():
    assert mcp_server._read_message(io.BytesIO(b"")) is None
    assert mcp_server._read_message(io.BytesIO(b"Content-Length: 0\r\n\r\n")) is None


def test_mcp_unknown_resource_and_prompt_errors():
    server = mcp_server.MCPServer()

    resource = server.handle({
        "jsonrpc": "2.0",
        "id": 1,
        "method": "resources/read",
        "params": {"uri": "dashboard://missing"},
    })
    prompt = server.handle({
        "jsonrpc": "2.0",
        "id": 2,
        "method": "prompts/get",
        "params": {"name": "missing"},
    })

    assert "Unknown resource" in resource["error"]["message"]
    assert "Unknown prompt" in prompt["error"]["message"]


def test_mcp_ping_unsupported_and_notification_error(monkeypatch):
    server = mcp_server.MCPServer()

    ping = server.handle({"jsonrpc": "2.0", "id": 1, "method": "ping"})
    unsupported = server.handle({"jsonrpc": "2.0", "id": 2, "method": "missing"})
    monkeypatch.setattr(mcp_server, "_log", lambda message: None)
    notification_error = server.handle({
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "missing_tool", "arguments": {}},
    })
    notification_success = server.handle({"jsonrpc": "2.0", "method": "ping"})

    assert ping["result"] == {}
    assert "Unsupported MCP method" in unsupported["error"]["message"]
    assert notification_error is None
    assert notification_success is None
