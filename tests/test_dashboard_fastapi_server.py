from pathlib import Path

from fastapi.testclient import TestClient

from dashboard import server


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_runtime_uses_fastapi_not_base_http_handler():
    source = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")

    assert "FastAPI" in source
    assert "uvicorn.run" in source
    assert "BaseHTTPRequestHandler" not in source
    assert "ThreadingHTTPServer" not in source


def test_dashboard_fastapi_auth_and_state_endpoint(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_AUTH_ENABLED", True)
    monkeypatch.setattr(server.config, "DASHBOARD_USERNAME", "admin")
    monkeypatch.setattr(server.config, "DASHBOARD_PASSWORD", "change-me")
    monkeypatch.setattr(server, "_adb_devices", lambda: [])

    client = TestClient(server.create_app(server.DashboardService()))

    unauthenticated = client.get("/api/state")
    assert unauthenticated.status_code == 401
    assert unauthenticated.json()["error"] == "authentication required"

    login = client.post("/api/login", json={"username": "admin", "password": "change-me"})
    assert login.status_code == 200
    assert login.json()["ok"] is True
    assert server.SESSION_COOKIE_NAME in login.cookies

    authenticated = client.get("/api/state")
    assert authenticated.status_code == 200
    assert authenticated.json()["methods"]["stages"]


def test_dashboard_fastapi_noauth_login_page_cannot_trap_user(monkeypatch):
    monkeypatch.setattr(server.config, "DASHBOARD_AUTH_ENABLED", False)
    monkeypatch.setattr(server, "_adb_devices", lambda: [])

    client = TestClient(server.create_app(server.DashboardService()))

    root = client.get("/")
    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-store"
    assert 'id="logoutBtn"' in root.text

    stale_login_submit = client.post("/api/login", json={"username": "wrong", "password": "wrong"})
    assert stale_login_submit.status_code == 200
    assert stale_login_submit.json()["ok"] is True


def test_ci_workflow_runs_secret_scan_tests_and_uploads_coverage():
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert 'python-version: "3.13"' in workflow
    assert "scripts/secret_scan.sh" in workflow
    assert "--cov-report=xml:coverage.xml" in workflow
    assert "reports/pytest-junit.xml" in workflow
    assert "actions/upload-artifact@v4" in workflow
