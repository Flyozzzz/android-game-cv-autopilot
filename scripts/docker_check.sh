#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

IMAGE="${IMAGE:-android-game-cv-autopilot:0.1.15c-beta}"

echo "EN: Building Docker image ${IMAGE}"
echo "RU: Собираем Docker image ${IMAGE}"
docker build -t "${IMAGE}" .

echo "EN: Running pytest inside Docker"
echo "RU: Запускаем pytest внутри Docker"
docker run --rm "${IMAGE}" python -m pytest -q

echo "EN: Running deterministic 100% coverage gate inside Docker"
echo "RU: Запускаем deterministic coverage gate 100% внутри Docker"
docker run --rm "${IMAGE}" python -m pytest \
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

echo "EN: Docker checks passed"
echo "RU: Docker проверки прошли"
