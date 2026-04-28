import hmac
import io
import json

from dashboard import mcp_server
from dashboard import server


def test_dashboard_auth_defaults_are_configurable():
    assert server._dashboard_auth_enabled() is True
    assert server._dashboard_username()
    assert server._dashboard_password()
    assert server._dashboard_mcp_api_key()


def test_dashboard_login_and_session_helpers(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_USERNAME", "admin")
    monkeypatch.setattr(server.config, "DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setattr(server.config, "DASHBOARD_SESSION_TTL_SECONDS", 60)

    assert server._login_matches("admin", "change-me") is True
    assert server._login_matches("admin", "bad") is False

    token = server._create_session("admin")
    assert token
    assert server._session_authorized(f"{server.SESSION_COOKIE_NAME}={token}") is True
    assert server._session_authorized(f"{server.SESSION_COOKIE_NAME}=missing") is False
    assert server._session_authorized("") is False


def test_dashboard_api_key_auth(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_MCP_API_KEY", "mcp-secret")

    assert server._api_key_authorized("mcp-secret") is True
    assert server._api_key_authorized("Bearer mcp-secret") is True
    assert server._api_key_authorized("bad") is False
    assert hmac.compare_digest(server._dashboard_mcp_api_key(), "mcp-secret")


def test_dashboard_public_paths_and_login_contract():
    login_html = (server.STATIC_DIR / "login.html").read_text(encoding="utf-8")

    assert server._is_public_path("/static/styles.css") is True
    assert server._is_public_path("/api/login") is True
    assert server._is_public_path("/api/state") is False
    assert 'id="loginForm"' in login_html
    assert 'id="loginUsername"' in login_html
    assert 'id="loginPassword"' in login_html
    assert "/api/login" in login_html
    assert 'id="logoutBtn"' in (server.STATIC_DIR / "index.html").read_text(encoding="utf-8")


def test_dashboard_rejects_public_bind_with_weak_defaults(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_AUTH_ENABLED", True)
    monkeypatch.setattr(server.config, "DASHBOARD_USERNAME", "admin")
    monkeypatch.setattr(server.config, "DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setattr(server.config, "DASHBOARD_MCP_API_KEY", "change-me")

    try:
        server._validate_dashboard_exposure("0.0.0.0")
    except RuntimeError as exc:
        assert "DASHBOARD_USERNAME" in str(exc)
    else:
        raise AssertionError("public bind with weak secrets must be rejected")


def test_dashboard_allows_public_bind_only_with_strong_secrets(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_AUTH_ENABLED", True)
    monkeypatch.setattr(server.config, "DASHBOARD_USERNAME", "operator")
    monkeypatch.setattr(server.config, "DASHBOARD_PASSWORD", "local-long-random-password")
    monkeypatch.setattr(server.config, "DASHBOARD_MCP_API_KEY", "local-long-random-mcp-key")

    server._validate_dashboard_exposure("0.0.0.0")


def test_dashboard_preset_cleaning_redacts_unknown_secret_shapes():
    handler = object.__new__(server.DashboardHandler)
    cleaned = handler._clean_preset_settings(
        {
            "settings": {
                "gameProfile": "demo",
                "nested": {"password": "hunter2"},
                "notes": "api_key=sk-or-v1-secret",
            }
        }
    )

    assert cleaned["nested"]["password"] == "[REDACTED]"
    assert "sk-or-v1" not in cleaned["notes"]


def test_mcp_requests_include_dashboard_api_key(monkeypatch):
    captured = {}

    class FakeResponse:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake_urlopen(request, timeout=120):
        captured["api_key"] = request.headers.get("X-dashboard-api-key")
        return FakeResponse()

    monkeypatch.setattr(mcp_server, "DASHBOARD_MCP_API_KEY", "mcp-secret")
    monkeypatch.setattr(mcp_server, "_ensure_dashboard", lambda: None)
    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)

    assert mcp_server._http_json("GET", "/api/state") == {"ok": True}
    assert captured["api_key"] == "mcp-secret"


def test_mcp_http_bytes_include_dashboard_api_key(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b"bytes"

    def fake_urlopen(request, timeout=60):
        captured["api_key"] = request.headers.get("X-dashboard-api-key")
        return FakeResponse()

    monkeypatch.setattr(mcp_server, "DASHBOARD_MCP_API_KEY", "mcp-secret")
    monkeypatch.setattr(mcp_server, "_ensure_dashboard", lambda: None)
    monkeypatch.setattr(mcp_server, "urlopen", fake_urlopen)

    assert mcp_server._http_bytes("/api/device/screenshot") == b"bytes"
    assert captured["api_key"] == "mcp-secret"
