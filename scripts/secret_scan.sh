#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PATTERN='(sk-or-v1-[A-Za-z0-9_-]{20,}|eyJhbGciOi[A-Za-z0-9_-]{20,}|AIza[0-9A-Za-z_-]{20,}|BROWSERSTACK_ACCESS_KEY\s*=\s*["'"'"'][^"'"'"']+|LT_ACCESS_KEY\s*=\s*["'"'"'][^"'"'"']+|FIVESIM_API_KEY\s*=\s*["'"'"'][^"'"'"']+|OPENROUTER_API_KEY\s*=\s*["'"'"'][^"'"'"']+)'

if rg -n --hidden --pcre2 \
  --glob '!.git/**' \
  --glob '!legacy/**' \
  --glob '!archive/**' \
  --glob '!logs/**' \
  --glob '!reports/**' \
  --glob '!trace/**' \
  --glob '!screenshots/**' \
  --glob '!dashboard/runs/**' \
  --glob '!__pycache__/**' \
  --glob '!.pytest_cache/**' \
  --glob '!.venv/**' \
  --glob '!credentials.json' \
  --glob '!CLAUDE.md' \
  --glob '!scripts/secret_scan.sh' \
  --glob '!.env' \
  --glob '!.env.*' \
  --glob '!latest_run.log' \
  -e "${PATTERN}" .; then
  echo "Potential secret material found in public surface."
  exit 1
fi

echo "No public-surface secrets detected."
