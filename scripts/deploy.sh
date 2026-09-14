#!/usr/bin/env bash
set -euo pipefail

REMOTE="${MEMORYLAYER_DEPLOY_REMOTE:-root@46.250.246.198}"
REMOTE_DIR="${MEMORYLAYER_DEPLOY_DIR:-/opt/engram-cloud}"
REF="${1:-HEAD}"
SHA="$(git rev-parse "$REF")"
[[ "$REMOTE_DIR" == /opt/engram-cloud ]] || { echo 'Review a nonstandard deployment directory manually.' >&2; exit 1; }
git diff --check
.venv/bin/python -m pytest -q

# Stage an immutable tree without touching the current service or persistent mounts.
ssh "$REMOTE" "mkdir -p '/opt/engram-cloud-releases/$SHA'"
git archive --format=tar "$SHA" | ssh "$REMOTE" "tar -xf - -C '/opt/engram-cloud-releases/$SHA'"
ssh "$REMOTE" bash -s -- "$SHA" <<'REMOTE_SCRIPT'
set -euo pipefail
sha="$1"
cd "/opt/engram-cloud-releases/$sha"
docker build --build-arg "SOURCE_REVISION=$sha" -t "engram-cloud:$sha" .
echo "Built engram-cloud:$sha. Validate this candidate before activation."
REMOTE_SCRIPT
printf 'Candidate staged: %s. Follow docs/deployment.md for isolated checks and backed-up activation.\n' "$SHA"
