#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${MEMORYLAYER_BASE_URL:-https://memorylayer.run}"

check_json() {
  local path="$1"
  curl -fsS "$BASE_URL$path" >/dev/null
  echo "ok $path"
}

check_page() {
  local path="$1"
  local needle="$2"
  curl -fsS "$BASE_URL$path" | grep -F "$needle" >/dev/null
  echo "ok $path contains $needle"
}

check_json "/api/service/readiness"
check_json "/api/service/architecture"
check_json "/api/service/manifest"
check_json "/api/service/deploy-plan"
check_page "/operations" "Deploy path"
check_page "/docs" "/api/workspaces/{slug}/observability"
check_page "/status" "Readiness checks"
