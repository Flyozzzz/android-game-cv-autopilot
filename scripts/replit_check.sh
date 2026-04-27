#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

python3 -m pip install --user -r requirements.txt
python3 -m compileall -q core dashboard scenarios services tests bootstrap.py main.py config.py
python3 -m pytest -q
python3 -m pytest \
  tests/test_dashboard_mcp_server.py \
  tests/test_cv_prompt_templates.py \
  tests/test_dashboard_cv_bridge.py \
  tests/test_game_profiles.py \
  --cov=dashboard.mcp_server \
  --cov=core.cv_prompt_templates \
  --cov=dashboard.cv_bridge \
  --cov=core.game_profiles \
  --cov-report=term-missing \
  --cov-fail-under=100 \
  -q
