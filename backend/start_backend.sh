#!/usr/bin/env bash
# Run from anywhere: points PYTHONPATH at the repo root so `backend.*` imports resolve.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
export PYTHONPATH="${REPO_ROOT}"
# Trust X-Forwarded-Proto from a reverse proxy (Render, nginx) so HTTPS detection works.
exec uvicorn backend.api.main:app --host 0.0.0.0 --port 8000 --reload \
  --proxy-headers --forwarded-allow-ips='*'
