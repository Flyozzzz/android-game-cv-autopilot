#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export DASHBOARD_HOST="${DASHBOARD_HOST:-0.0.0.0}"
export DASHBOARD_PORT="${DASHBOARD_PORT:-8765}"
export DASHBOARD_AUTH_ENABLED="${DASHBOARD_AUTH_ENABLED:-1}"
export DASHBOARD_USERNAME="${DASHBOARD_USERNAME:-admin}"
export DASHBOARD_PASSWORD="${DASHBOARD_PASSWORD:-}"
export DASHBOARD_MCP_API_KEY="${DASHBOARD_MCP_API_KEY:-}"
export LOCAL_DEVICE="${LOCAL_DEVICE:-auto}"
export PURCHASE_MODE="preview"
export GOOGLE_PHONE_MODE="manual"
export MCP_AUTOSTART_DASHBOARD="${MCP_AUTOSTART_DASHBOARD:-0}"
export PYTHONUNBUFFERED=1

python3 -m pip install --user -r requirements.txt

if [[ -z "${DASHBOARD_PASSWORD}" || -z "${DASHBOARD_MCP_API_KEY}" ]]; then
  echo "Set DASHBOARD_PASSWORD and DASHBOARD_MCP_API_KEY in Replit Secrets before starting the public dashboard." >&2
  exit 1
fi

if [[ "${REPLIT_INSTALL_PLAYWRIGHT:-0}" == "1" ]]; then
  python3 -m playwright install chromium
fi

echo "Starting dashboard on ${DASHBOARD_HOST}:${DASHBOARD_PORT}"
echo "Login: ${DASHBOARD_USERNAME} / <DASHBOARD_PASSWORD>"
echo "MCP API key env: DASHBOARD_MCP_API_KEY"
echo "Cloud Replit cannot see a USB phone from your computer; use a remote farm or an ADB target reachable from the Repl."

exec python3 -m dashboard.server
