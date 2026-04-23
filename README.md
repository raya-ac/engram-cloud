# Engram Cloud

Hosted service layer for [Engram](https://github.com/raya-ac/engram): GitHub login, shared workspaces, API keys, invite flow, a hosted MCP bridge, downloadable starter skills, and a dashboard that makes the memory engine usable as a service.

## Why this exists

Engram is strong as a local engine. A hosted version needs a different layer around it:

- user identity
- workspace isolation
- service auth
- audit history
- a deployment model that fits a long-lived memory process

This repo is that wrapper.

## Hosting choice

Recommended: **VPS**

Why:

- Engram wants a long-lived Python process
- direct Postgres access is simpler
- background ingestion is easier
- future MCP and websocket work fits more naturally

Vercel is fine for:

- marketing pages
- auth shell
- a thin frontend

For the actual memory runtime, a VPS is the clean default.

## What is in the repo right now

- GitHub OAuth login
- user/workspace metadata in Postgres
- one Engram-backed workspace store per workspace
- dashboard to create workspaces, inspect stats, search memory, and write memories
- workspace invites
- workspace API keys
- audit trail for workspace actions
- JSON endpoints for search, remember, status, recent memories, and audit history
- workspace bootstrap endpoint for agents
- hosted MCP-style bridge for selected Engram tools
- starter skill downloads in JSON and markdown
- public docs and pricing pages for the hosted service

## Stack

- FastAPI
- Jinja templates
- SQLAlchemy
- Authlib GitHub OAuth
- Postgres
- `engram-memory-system`

## Local setup

1. Copy `.env.example` to `.env`
2. Set GitHub OAuth credentials
3. Start Postgres
4. Install dependencies

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --port 8090
```

Open:

- [http://127.0.0.1:8090](http://127.0.0.1:8090)

Run tests:

```bash
pytest -q
```

## Environment

Required:

- `ENGRAM_CLOUD_SECRET_KEY`
- `ENGRAM_CLOUD_BASE_URL`
- `ENGRAM_CLOUD_POSTGRES_DSN`
- `ENGRAM_CLOUD_ENGRAM_POSTGRES_DSN`
- `ENGRAM_CLOUD_GITHUB_CLIENT_ID`
- `ENGRAM_CLOUD_GITHUB_CLIENT_SECRET`

## Storage model

This service uses:

- one shared Postgres database for app metadata
- one Engram schema per workspace for memory data

That keeps the service layer separate from the memory layer while still using the Engram package directly.

## Deployment

### VPS

Use:

- `Dockerfile`
- `docker-compose.yml`

Run behind Caddy or nginx with HTTPS.

### Vercel

Not recommended as the primary memory backend runtime.

If you want, use Vercel later for:

- a separate frontend shell
- marketing/docs
- auth-only surfaces

while the real Engram runtime lives on a VPS.

## Agent integration

Each workspace can expose:

- `GET /api/workspaces/{slug}/bootstrap`
- `GET /api/workspaces/{slug}/status`
- `GET /api/workspaces/{slug}/memories/recent`
- `POST /api/workspaces/{slug}/search`
- `POST /api/workspaces/{slug}/remember`
- `GET /api/workspaces/{slug}/audit`
- `GET /api/workspaces/{slug}/mcp/tools`
- `POST /api/workspaces/{slug}/mcp`

The service also exposes starter skills:

- `GET /api/skills`
- `GET /api/skills/{name}`
- `GET /api/skills/{name}.md`
