from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_replit_runs_dashboard_server_with_safe_defaults():
    replit = (ROOT / ".replit").read_text(encoding="utf-8")
    start = (ROOT / "scripts/replit_start.sh").read_text(encoding="utf-8")
    server = (ROOT / "dashboard/server.py").read_text(encoding="utf-8")

    assert 'run = "bash scripts/replit_start.sh"' in replit
    assert 'DASHBOARD_HOST = "0.0.0.0"' in replit
    assert 'DASHBOARD_PORT = "8765"' in replit
    assert 'PURCHASE_MODE = "preview"' in replit
    assert 'GOOGLE_PHONE_MODE = "manual"' in replit
    assert 'Set DASHBOARD_PASSWORD and DASHBOARD_MCP_API_KEY' in start
    assert 'Login: ${DASHBOARD_USERNAME} / <DASHBOARD_PASSWORD>' in start
    assert 'exec python3 -m dashboard.server' in start
    assert 'os.getenv("DASHBOARD_HOST", "127.0.0.1")' in server


def test_replit_helper_scripts_cover_checks_and_mcp():
    check = (ROOT / "scripts/replit_check.sh").read_text(encoding="utf-8")
    mcp = (ROOT / "scripts/replit_mcp.sh").read_text(encoding="utf-8")
    nix = (ROOT / "replit.nix").read_text(encoding="utf-8")

    assert "python3 -m pytest -q" in check
    assert "--cov-fail-under=100" in check
    assert 'Set DASHBOARD_MCP_API_KEY' in mcp
    assert "exec python3 -m dashboard.mcp_server" in mcp
    assert "pkgs.android-tools" in nix
    assert "pkgs.nodejs_20" in nix
