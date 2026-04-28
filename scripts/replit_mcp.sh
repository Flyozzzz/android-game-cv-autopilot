#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export DASHBOARD_URL="${DASHBOARD_URL:-http://127.0.0.1:8765}"
export DASHBOARD_MCP_API_KEY="${DASHBOARD_MCP_API_KEY:-}"
export MCP_AUTOSTART_DASHBOARD="${MCP_AUTOSTART_DASHBOARD:-0}"

python3 -m pip install --user -r requirements.txt
if [[ -z "${DASHBOARD_MCP_API_KEY}" ]]; then
  echo "Set DASHBOARD_MCP_API_KEY in Replit Secrets before starting MCP." >&2
  exit 1
fi
exec python3 -m dashboard.mcp_server
