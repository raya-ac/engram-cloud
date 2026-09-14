# memory layer

Engram Cloud runs [Memory Layer](https://memorylayer.run), the hosted service for [Engram](https://github.com/raya-ac/engram) and [Mythic](https://github.com/raya-ac/mythic).

Sign in with GitHub, create a workspace, and give your agents a place to keep useful context. You can search and write memories, import notes, manage access, and see what each API key has been doing. Open **Cognition** inside a workspace to work with Mythic sessions and their decision history.

## memory and cognition

Engram handles memory storage and retrieval. The workspace UI covers search, recent memories, ingestion, keys, invites, audit history, and usage. Imports accept pasted text or files, with paragraph, line, markdown, CSV, JSON, and single-memory splitting. Preview an import before writing it. Recent exports are useful for inspection; a complete backup needs the database and persistent files.

Mythic keeps sessions, planner tasks, assumptions, observations, and decisions. A cycle recalls a bounded set of workspace memories through lexical search and records the planning state without reinforcing those memories. Normal Engram hybrid search is still available through the memory API.

An assumption starts unknown. You can check whether Engram is connected or advertises a particular tool, then record a proceed, hold, or revise decision. Checks never execute the proposed action. Server files, shell commands, plugins, and guessed workstation state are outside the hosted check registry.

Observed evidence can be published explicitly to Engram. It keeps its source, expiry, and lifecycle state, including forgetting. `verified_by_engram=false` means storage isn't an independent verification claim. Dormant review, inspection, and feedback are available; automatic dormant collection stays off.

The cognition setting controls new Mythic writes and cycles for the workspace. Turning it off keeps saved sessions available to read. Kiln is optional: the hosted UI and APIs work independently of it.

## connect an agent

Create a workspace API key, then open its connection kit. It provides a bootstrap response, environment file, agent configuration, a Codex-side launcher profile, and a Claude skill. Keys stay scoped to their workspace.

The hosted MCP-style adapter uses an HTTP JSON `tool`/`args` envelope. Any client that can make authenticated HTTP requests can use it, including Python, JavaScript, shell scripts, and custom agent launchers. The [SDK page](https://memorylayer.run/sdks) has working request shapes; the [API explorer](https://memorylayer.run/api-explorer) documents the endpoints.

```bash
export MEMORYLAYER_URL=https://memorylayer.run
export MEMORYLAYER_WORKSPACE=your-workspace
# Set MEMORYLAYER_API_KEY from your secret manager or shell environment.

curl -H "Authorization: Bearer $MEMORYLAYER_API_KEY" \
  "$MEMORYLAYER_URL/api/workspaces/$MEMORYLAYER_WORKSPACE/mcp/tools"

curl -H "Authorization: Bearer $MEMORYLAYER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"tool":"recall","args":{"query":"current project decisions","top_k":5}}' \
  "$MEMORYLAYER_URL/api/workspaces/$MEMORYLAYER_WORKSPACE/mcp"
```

Mythic is available through the same adapter with names such as `mythic_session_start`, or through its dedicated API:

```bash
curl -H "Authorization: Bearer $MEMORYLAYER_API_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"operation":"session_start","params":{"project_id":"release","goal":"prepare the next release"}}' \
  "$MEMORYLAYER_URL/api/workspaces/$MEMORYLAYER_WORKSPACE/mythic"
```

Keep the returned session ID for later cycles, checks, and resume requests. `project_id` is a logical label within the authenticated workspace. It cannot select a filesystem path or another workspace's store.

The workspace API prefix is `/api/workspaces/{slug}`:

| use | endpoints |
|---|---|
| connection setup | `GET /bootstrap`, `/connect`, `/env`, `/agent-config`, `/codex.toml`, `/claude-skill.md` |
| memory | `GET /status`, `/memories/recent`; `POST /search`, `/remember` |
| imports and exports | `POST /ingest/preview`, `/ingest`; `GET /ingest/runs`, `/export/recent` |
| operations | `GET /audit`, `/usage`, `/observability` |
| tool adapter | `GET /mcp/tools`; `POST /mcp` |
| cognition | `GET /mythic` for discovery/settings/status; `POST /mythic` for operations |

Tool discovery includes schemas for retrieval, handoffs, curation, evidence, dormant review, and Mythic. Starter skills are also available at `/api/skills`, `/api/skills/{name}`, and `/api/skills/{name}.md`. The native JSONL interfaces belong to the standalone cores; use the hosted HTTP endpoints here.

## run it locally

The service uses FastAPI, Jinja, SQLAlchemy, Authlib, and PostgreSQL. Both core packages are pinned to Git revisions in [pyproject.toml](pyproject.toml).

For Docker, copy [.env.example](.env.example) to `.env` and set a random secret of at least 32 characters plus your GitHub OAuth credentials. Register the callback as `http://127.0.0.1:8090/auth/github/callback`. For the local Compose setup, use:

```dotenv
ENGRAM_CLOUD_BASE_URL=http://127.0.0.1:8090
ENGRAM_CLOUD_SECURE_COOKIES=false
ENGRAM_CLOUD_POSTGRES_DSN=postgresql+psycopg://engram:engram@postgres:5432/engram_cloud
ENGRAM_CLOUD_ENGRAM_POSTGRES_DSN=postgresql://engram:engram@postgres:5432/engram_cloud
ENGRAM_CLOUD_DATA_DIR=./data
```

```bash
cp .env.example .env
# Edit .env before starting the containers.
docker compose up --build
```

Open [localhost:8090](http://127.0.0.1:8090). The model cache may need to download the embedding and reranker models on first use.

For Python development, use Python 3.12, Git, a C++ build toolchain, and a reachable PostgreSQL instance. Point both database settings at that instance instead of the Compose hostname `postgres`.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m uvicorn app.main:app --reload --port 8090
```

## configuration and storage

`ENGRAM_CLOUD_SECRET_KEY`, `ENGRAM_CLOUD_BASE_URL`, both database DSNs, and the GitHub client ID/secret define the service connection. Keep `.env` out of Git. For HTTPS, use the public base URL and secure cookies, with a matching OAuth callback.

[app/config.py](app/config.py) contains the defaults and supported controls:

| setting | purpose |
|---|---|
| `ENGRAM_CLOUD_DATA_DIR` | persistent workspace files and Mythic state |
| `ENGRAM_CLOUD_ALLOWED_HOSTS` | accepted request hosts |
| `ENGRAM_CLOUD_SECURE_COOKIES` | HTTPS-only session cookies |
| `ENGRAM_CLOUD_SESSION_MAX_AGE_SECONDS` | session lifetime |
| `ENGRAM_CLOUD_MAX_REQUEST_BYTES` | request body limit |
| `ENGRAM_CLOUD_AUTH_RATE_LIMIT_PER_MINUTE` | sign-in request limit |
| `ENGRAM_CLOUD_API_RATE_LIMIT_PER_MINUTE` | workspace API request limit |
| `ENGRAM_CLOUD_SOURCE_REVISION` | deployed source revision reported by service metadata |

App accounts, membership, keys, and audit records live in the shared PostgreSQL schema. Each workspace has its own Engram schema and index files. Mythic stores live under `data/<workspace>/mythic/`, with separate project directories and a persistent workspace setting.

Mythic opens and closes a service for each operation. The adapter bounds lock waits, database work, request size, projects, sessions, events, and storage. See [app/mythic_service.py](app/mythic_service.py) for the current limits. Save the full database and data directory together when making a backup; use a consistent SQLite backup or pause writes when copying active Mythic stores.

## checks and deployment

```bash
.venv/bin/python -m pytest -q
```

PostgreSQL compatibility cases need `ENGRAM_TEST_POSTGRES_DSN` pointing at a disposable test database. Create that database separately from application data; without the setting, those cases are skipped.

```bash
ENGRAM_TEST_POSTGRES_DSN='postgresql://engram:engram@127.0.0.1:5432/engram_cloud_test' \
  .venv/bin/python -m pytest -q
```

The hosted service runs as a persistent Docker Compose app behind Layerline on the VPS. The release script runs local checks and builds a candidate from an exact commit:

```bash
scripts/deploy.sh HEAD
```

Activation is a separate step after candidate checks and backups. [docs/deployment.md](docs/deployment.md) covers the image override, persistent mounts, origin checks, and rollback. It also covers `Dockerfile.release` for building over an existing dependency image. Preserve the old image and database backup before switching a release.

The [service manifest](https://memorylayer.run/api/service/manifest) reports source revisions, including installed core provenance. `/api/service/readiness` checks the database and service configuration; `/api/service/status`, `/api/service/architecture`, and `/api/service/deploy-plan` expose the other operational details. `/openapi.json` describes the HTTP routes.

## docs

The hosted [docs](https://memorylayer.run/docs) link to architecture, integrations, use cases, operations, security, examples, SDK snippets, capabilities, and the changelog. Machine-readable versions include `/api/capabilities`, `/api/mcp/manifest`, `/api/sdk-snippets`, `/api/playbooks`, and `/api/examples`.

[engram-memory.dev](https://engram-memory.dev) documents the standalone Engram core. Memory Layer is hosted at [memorylayer.run](https://memorylayer.run); the two sites have separate deployments.

## license

Engram Cloud (Memory Layer) uses the [Engram Cloud Access License 1.0](LICENSE). It is proprietary. Repository access does not grant permission to use or redistribute it; use requires explicit prior written permission from raya-ac.

Engram, Mythic, and other third-party material retain their own copyrights and licenses. This change does not replace those terms or alter rights granted under earlier licenses.
