# Memorylayer deployment

Memorylayer deploys as one Docker Compose service on the VPS. The app directory keeps `.env`, `docker-compose.yml`, and the persistent `data/` mount on the server; application code is streamed from the local git tree with `git archive`.

## Standard deploy

```bash
scripts/deploy.sh
```

The script runs:

- `git diff --check`
- `.venv/bin/python -m pytest -q`
- `.venv/bin/python -m compileall app`
- `git archive HEAD | ssh ... tar -xf - -C /opt/engram-cloud`
- `docker compose up -d --build web`
- `scripts/live-check.sh`

## Useful environment overrides

```bash
MEMORYLAYER_DEPLOY_REMOTE=root@46.250.246.198 scripts/deploy.sh
MEMORYLAYER_DEPLOY_DIR=/opt/engram-cloud scripts/deploy.sh
MEMORYLAYER_BASE_URL=https://memorylayer.run scripts/live-check.sh
SKIP_TESTS=1 scripts/deploy.sh
```

Use `SKIP_TESTS=1` only for emergency template-only fixes after local verification has already passed.

## Live checks

```bash
scripts/live-check.sh
```

The live check verifies readiness, architecture, manifest, deploy-plan JSON, and key rendered pages. A release is not done until the live checks pass.
