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
- structured API usage tracking per workspace key
- paste, file, and batch API ingestion into workspace memory
- ingestion run history with source metadata and item counts
- JSON endpoints for search, remember, status, recent memories, audit history, and usage history
- recent memory export endpoint for backups and inspection
- warm workspace runtime cache so search and memory writes do not rebuild Engram state on every request
- workspace bootstrap endpoint for agents
- hosted MCP-style bridge for retrieval, handoff, skills, curation, and memory health tools
- public capability index with 100+ service, site, and agent-facing capabilities
- public service, capability, and MCP manifests for clients and agent launchers
- SDK snippet and playbook pages plus JSON endpoints
- API explorer with request and response fixtures for client builders
- workspace connection kit endpoints for agent config JSON and `.env` generation
- hardened browser and API boundary with CSP, frame blocking, host/origin checks, request-size limits, safer session cookies, basic throttles, malformed JSON accounting, and probe-path blocking
- starter skill downloads in JSON and markdown
- public docs, examples, service status, security, and changelog pages
- robots.txt and sitemap.xml for the public site

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
- [http://127.0.0.1:8090/docs](http://127.0.0.1:8090/docs)
- [http://127.0.0.1:8090/connect](http://127.0.0.1:8090/connect)
- [http://127.0.0.1:8090/examples](http://127.0.0.1:8090/examples)
- [http://127.0.0.1:8090/api-explorer](http://127.0.0.1:8090/api-explorer)
- [http://127.0.0.1:8090/sdks](http://127.0.0.1:8090/sdks)
- [http://127.0.0.1:8090/security](http://127.0.0.1:8090/security)
- [http://127.0.0.1:8090/status](http://127.0.0.1:8090/status)

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

Security controls:

- `ENGRAM_CLOUD_ALLOWED_HOSTS`
- `ENGRAM_CLOUD_SECURE_COOKIES`
- `ENGRAM_CLOUD_SESSION_MAX_AGE_SECONDS`
- `ENGRAM_CLOUD_MAX_REQUEST_BYTES`
- `ENGRAM_CLOUD_AUTH_RATE_LIMIT_PER_MINUTE`
- `ENGRAM_CLOUD_API_RATE_LIMIT_PER_MINUTE`

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
- `GET /api/workspaces/{slug}/connect`
- `GET /api/workspaces/{slug}/env`
- `GET /api/workspaces/{slug}/status`
- `GET /api/workspaces/{slug}/memories/recent`
- `POST /api/workspaces/{slug}/search`
- `POST /api/workspaces/{slug}/remember`
- `POST /api/workspaces/{slug}/ingest`
- `GET /api/workspaces/{slug}/audit`
- `GET /api/workspaces/{slug}/usage`
- `GET /api/workspaces/{slug}/ingest/runs`
- `GET /api/workspaces/{slug}/export/recent`
- `GET /api/workspaces/{slug}/mcp/tools`
- `POST /api/workspaces/{slug}/mcp`

The bridge includes tool discovery with argument hints. Current tools cover:

- status, health, memory map, quality metrics, and grouped counts
- recall, compact context, hints, recent memories, entity lookup, and fuzzy entity search
- focused task briefs, layered prompt context, and procedural skill selection
- remember, decisions, errors, interactions, negative knowledge, and project state
- session checkpoints, handoff snapshots, and resume context
- hotspots, query comparison, export, memory status history, tags, pin, and forget

The service also exposes starter skills:

- `GET /api/skills`
- `GET /api/skills/{name}`
- `GET /api/skills/{name}.md`

Public service metadata:

- `GET /api/health`
- `GET /api/service/status` including runtime cache metrics
- `GET /capabilities` for the public capability index
- `GET /api/service/manifest`
- `GET /api/capabilities`
- `GET /api/mcp/manifest`
- `GET /api/sdk-snippets`
- `GET /api/playbooks`
- `GET /api/examples`
- `GET /robots.txt`
- `GET /sitemap.xml`

## License

Proprietary. All rights reserved. See [LICENSE](LICENSE).
