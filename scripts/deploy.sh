#!/usr/bin/env bash
set -euo pipefail

REMOTE="${MEMORYLAYER_DEPLOY_REMOTE:-root@46.250.246.198}"
REMOTE_DIR="${MEMORYLAYER_DEPLOY_DIR:-/opt/engram-cloud}"
REF="${1:-HEAD}"

if [[ "${SKIP_TESTS:-0}" != "1" ]]; then
  git diff --check
  .venv/bin/python -m pytest -q
  .venv/bin/python -m compileall app
fi

ARCHIVE_SHA="$(git rev-parse --short "$REF")"
echo "Deploying $ARCHIVE_SHA to $REMOTE:$REMOTE_DIR"

git archive --format=tar "$REF" \
  | ssh "$REMOTE" "mkdir -p '$REMOTE_DIR' && tar -xf - -C '$REMOTE_DIR'"

ssh "$REMOTE" "cd '$REMOTE_DIR' && docker compose up -d --build web"

scripts/live-check.sh
