from __future__ import annotations

import json
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from sqlalchemy import false, func, select
from sqlalchemy import delete

from app.agent_catalog import STARTER_SKILLS, SUPPORTED_TOOLS, grouped_tool_list, render_skill_markdown, starter_skill_list
from app.auth import current_user_id, login_required, oauth
from app.config import settings
from app.db import Base, SessionLocal, engine
from app.engram_service import (
    close_workspace_runtimes,
    init_workspace_store,
    schema_name_for_slug,
    workspace_runtime_stats,
    slugify,
    workspace_recent_memories,
    workspace_remember,
    workspace_search,
    workspace_status,
    workspace_tool_call,
)
from app.hardening import RequestGuardMiddleware, SecurityHeadersMiddleware
from app.models import (
    AuditEvent,
    User,
    Workspace,
    WorkspaceApiEvent,
    WorkspaceApiKey,
    WorkspaceIngestRun,
    WorkspaceInvite,
    WorkspaceMember,
    utc_now,
)
from app.security import digest_token, mint_prefixed_token


@asynccontextmanager
async def lifespan(_app: FastAPI):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(engine)
    try:
        yield
    finally:
        close_workspace_runtimes()


app = FastAPI(title="Engram Cloud", version="0.1.0", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestGuardMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    https_only=settings.cookie_https_only(),
    same_site="lax",
    max_age=settings.session_max_age_seconds,
    session_cookie="memorylayer_session",
)
app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "static")), name="static")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


SERVICE_FEATURES = [
    {"name": "Workspace isolation", "summary": "Each workspace receives its own Engram schema and service boundary."},
    {"name": "GitHub login", "summary": "User identity is handled through GitHub OAuth with no local passwords."},
    {"name": "Workspace invites", "summary": "Issue shareable invites with role-aware membership records."},
    {"name": "Scoped API keys", "summary": "Generate workspace keys for agents, apps, and ingestion pipelines."},
    {"name": "API usage trail", "summary": "Track service calls by route, key, and workspace."},
    {"name": "Audit history", "summary": "Record workspace actions such as keys, invites, memory writes, and bridge calls."},
    {"name": "Hosted MCP bridge", "summary": "Call selected Engram tools through a simple HTTP JSON bridge."},
    {"name": "Bootstrap payloads", "summary": "Discover URLs, headers, tools, and skills from one workspace endpoint."},
    {"name": "Starter skills", "summary": "Download markdown skills that teach agents how to use hosted memory."},
    {"name": "Recent memory API", "summary": "Load the latest workspace memories without custom query code."},
    {"name": "Search API", "summary": "Run hosted retrieval against the real Engram memory graph."},
    {"name": "Remember API", "summary": "Store narrative, fact, and procedure memories over HTTP."},
    {"name": "Decision memory", "summary": "Bridge tool support for durable decisions and rationale."},
    {"name": "Project memory", "summary": "Bridge tool support for structured project state."},
    {"name": "Focus briefs", "summary": "Generate compact task context from the memory graph."},
    {"name": "Hotspot detection", "summary": "Find dense or high-activity regions in workspace memory."},
    {"name": "Query comparison", "summary": "Compare retrieval overlap between two prompts or topics."},
    {"name": "OpenAPI contract", "summary": "Expose the machine-readable API contract for clients."},
    {"name": "VPS runtime", "summary": "Run a warm Python service with direct Postgres access."},
    {"name": "Postgres-first storage", "summary": "Keep app metadata and Engram workspace data in Postgres."},
    {"name": "Dashboard search", "summary": "Search and inspect workspace memory from the browser."},
    {"name": "Dashboard write path", "summary": "Store memories manually when an operator needs to pin state."},
    {"name": "Key revocation", "summary": "Revoke workspace API keys without touching the memory store."},
    {"name": "Public service docs", "summary": "Keep setup, endpoints, bridge tools, and skills documented in-app."},
    {"name": "Paste ingestion", "summary": "Import pasted notes, transcripts, reports, or logs directly from a workspace."},
    {"name": "File ingestion", "summary": "Upload a text, markdown, JSON, or CSV-like file and split it into memories."},
    {"name": "Batch ingest API", "summary": "Push many memories in one authenticated request."},
    {"name": "Import run history", "summary": "Track source, type, item count, and actor for each ingestion run."},
    {"name": "Recent export", "summary": "Download recent workspace memories as JSON for inspection or backup."},
    {"name": "Connection kits", "summary": "Generate workspace-specific client config, env blocks, and startup calls."},
    {"name": "Agent config API", "summary": "Expose a normalized JSON profile that agents can read on boot."},
    {"name": "Env template API", "summary": "Return a copyable .env block for local workers and agent launchers."},
    {"name": "Connect page", "summary": "Document the shortest path from workspace key to working agent memory."},
]


INTEGRATION_RECIPES = [
    {
        "name": "Codex-style handoff",
        "steps": ["Load bootstrap", "Recall recent context", "Work normally", "Remember outcome"],
        "command": "curl -H \"Authorization: Bearer $MEMORYLAYER_KEY\" \"$MEMORYLAYER_URL/api/workspaces/$SLUG/bootstrap\"",
    },
    {
        "name": "Hosted MCP bridge",
        "steps": ["List bridge tools", "POST tool name and args", "Store audit trail"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"recall_recent\",\"args\":{\"limit\":5}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Ingestion pipeline",
        "steps": ["Create a service key", "POST memories", "Watch usage events"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"source_name\":\"handoff.md\",\"items\":[\"Deployment completed\",\"Follow up on billing UI\"],\"layer\":\"episodic\",\"memory_type\":\"fact\"}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/ingest\"",
    },
    {
        "name": "Usage monitor",
        "steps": ["Poll usage endpoint", "Group by route", "Rotate quiet or noisy keys"],
        "command": "curl -H \"Authorization: Bearer $MEMORYLAYER_KEY\" \"$MEMORYLAYER_URL/api/workspaces/$SLUG/usage\"",
    },
    {
        "name": "Compact prompt context",
        "steps": ["Call MCP bridge", "Fetch recall_context", "Inject result"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"recall_context\",\"args\":{\"query\":\"current project state\",\"max_tokens\":1200}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Session checkpoint",
        "steps": ["Summarize work", "Save checkpoint", "Resume later"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"session_checkpoint\",\"args\":{\"note\":\"Finished deploy; next check onboarding flow\",\"limit\":8}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Negative knowledge",
        "steps": ["Catch bad assumption", "Store exclusion", "Prevent repeat"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"remember_negative\",\"args\":{\"content\":\"Do not use local SQLite for production memory\",\"scope\":\"deployment\",\"context\":\"Postgres is required for hosted workspaces\"}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Entity pivot",
        "steps": ["Find entity", "Load graph", "Follow related work"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"entity_graph\",\"args\":{\"name\":\"Memorylayer\"}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Curation pass",
        "steps": ["Find duplicate cluster", "Deduplicate", "Check quality"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"dedup\",\"args\":{\"threshold\":0.92,\"max_merges\":5}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
    {
        "name": "Tool manifest",
        "steps": ["Fetch manifest", "Group tools", "Render client UI"],
        "command": "curl \"$MEMORYLAYER_URL/api/mcp/manifest\"",
    },
    {
        "name": "Public capability sync",
        "steps": ["Fetch capabilities", "Cache counts", "Expose service map"],
        "command": "curl \"$MEMORYLAYER_URL/api/capabilities\"",
    },
    {
        "name": "Workspace health check",
        "steps": ["Call health", "Read memory map", "Export recent"],
        "command": "curl -X POST -H \"Authorization: Bearer $MEMORYLAYER_KEY\" -H \"Content-Type: application/json\" -d '{\"tool\":\"health\",\"args\":{}}' \"$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp\"",
    },
]


SDK_SNIPPETS = [
    {
        "name": "JavaScript fetch",
        "language": "javascript",
        "summary": "Call the hosted bridge from a Node or browser-side tool runner.",
        "code": """const response = await fetch(`${MEMORYLAYER_URL}/api/workspaces/${SLUG}/mcp`, {
  method: "POST",
  headers: {
    "Authorization": `Bearer ${MEMORYLAYER_KEY}`,
    "Content-Type": "application/json"
  },
  body: JSON.stringify({
    tool: "recall_context",
    args: { query: "current project state", max_tokens: 1200 }
  })
});

const payload = await response.json();
console.log(payload.result);""",
    },
    {
        "name": "Python requests",
        "language": "python",
        "summary": "Use Memorylayer from scripts, workers, or custom agent harnesses.",
        "code": """import os
import requests

base = os.environ["MEMORYLAYER_URL"]
slug = os.environ["SLUG"]
key = os.environ["MEMORYLAYER_KEY"]

response = requests.post(
    f"{base}/api/workspaces/{slug}/mcp",
    headers={"Authorization": f"Bearer {key}"},
    json={"tool": "session_checkpoint", "args": {"note": "handoff saved", "limit": 8}},
    timeout=30,
)
response.raise_for_status()
print(response.json()["result"])""",
    },
    {
        "name": "Shell recall",
        "language": "shell",
        "summary": "Small curl call for debugging keys and tool output.",
        "code": """curl -X POST \\
  -H "Authorization: Bearer $MEMORYLAYER_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"tool":"recall_hints","args":{"query":"billing work","top_k":5}}' \\
  "$MEMORYLAYER_URL/api/workspaces/$SLUG/mcp" """,
    },
    {
        "name": "Agent bootstrap",
        "language": "shell",
        "summary": "Fetch workspace-specific URLs, skills, headers, and tool discovery.",
        "code": """curl -H "Authorization: Bearer $MEMORYLAYER_KEY" \\
  "$MEMORYLAYER_URL/api/workspaces/$SLUG/bootstrap" """,
    },
    {
        "name": "Batch ingest",
        "language": "shell",
        "summary": "Push a small handoff or imported dataset into workspace memory.",
        "code": """curl -X POST \\
  -H "Authorization: Bearer $MEMORYLAYER_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{"source_name":"handoff.md","source_type":"handoff","items":["Shipped manifest endpoints","Next: test onboarding"],"memory_type":"fact"}' \\
  "$MEMORYLAYER_URL/api/workspaces/$SLUG/ingest" """,
    },
    {
        "name": "MCP manifest client",
        "language": "javascript",
        "summary": "Build a tool picker from the public MCP manifest.",
        "code": """const manifest = await fetch(`${MEMORYLAYER_URL}/api/mcp/manifest`).then((r) => r.json());
for (const group of manifest.tool_groups) {
  console.log(group.name, group.tools.map((tool) => tool.name));
}""",
    },
]


PLAYBOOKS = [
    {
        "name": "New agent session",
        "steps": ["Fetch bootstrap", "Load resume_context", "Call get_skills", "Use recall_context", "Save session_checkpoint"],
        "outcome": "The agent starts with useful state and leaves a handoff behind.",
    },
    {
        "name": "Repository handoff",
        "steps": ["Ingest summary", "remember_project", "remember_decision", "session_handoff", "export recent"],
        "outcome": "A repo can be picked up by another session without reading stale chat logs.",
    },
    {
        "name": "Memory cleanup",
        "steps": ["quality_metrics", "dedup", "batch_tag", "promote/demote", "status_history"],
        "outcome": "Operators can keep the workspace useful instead of letting memories rot.",
    },
    {
        "name": "Investigation pivot",
        "steps": ["search_entities", "entity_graph", "recall_related", "backlinks", "focus_brief"],
        "outcome": "A single entity becomes a navigable map of prior work.",
    },
    {
        "name": "Client onboarding",
        "steps": ["service manifest", "MCP manifest", "capability JSON", "copy SDK snippet", "test status"],
        "outcome": "A custom client can wire itself without hardcoded docs.",
    },
]


CAPABILITY_GROUPS = [
    {
        "name": "Agent runtime",
        "items": [
            "workspace bootstrap",
            "HTTP MCP bridge",
            "tool discovery",
            "argument hints",
            "starter skills",
            "OpenAPI contract",
            "copyable recipes",
            "agent setup page",
            "workspace-scoped keys",
            "usage-visible agent calls",
        ],
    },
    {
        "name": "Retrieval",
        "items": [
            "semantic recall",
            "compact recall context",
            "recognition hints",
            "recent memory lookup",
            "fact-only retrieval",
            "procedure-aware retrieval",
            "full-context retrieval",
            "retrieval explanations",
            "query comparison",
            "compressed query summaries",
        ],
    },
    {
        "name": "Knowledge graph",
        "items": [
            "entity search",
            "entity graph export",
            "entity timeline",
            "related entity traversal",
            "memory backlinks",
            "similar memory lookup",
            "entity aliases",
            "entity metadata",
            "entity merge",
            "community detection",
        ],
    },
    {
        "name": "Memory writes",
        "items": [
            "narrative memory",
            "fact memory",
            "procedure memory",
            "decision memory",
            "error memory",
            "negative knowledge",
            "interaction capture",
            "project state",
            "session diary",
            "manual dashboard writes",
        ],
    },
    {
        "name": "Session continuity",
        "items": [
            "session checkpoint",
            "session handoff",
            "resume context",
            "session summary",
            "recent activity",
            "handoff starter skill",
            "workspace memory skill",
            "task skill selection",
            "layered prompt context",
            "focus briefs",
        ],
    },
    {
        "name": "Curation",
        "items": [
            "memory annotate",
            "memory edit",
            "memory invalidate",
            "status transitions",
            "status history",
            "tag add",
            "tag remove",
            "batch tagging",
            "pin memory",
            "forget memory",
        ],
    },
    {
        "name": "Maintenance",
        "items": [
            "promote memory",
            "demote memory",
            "unpin memory",
            "link memories",
            "deduplicate memories",
            "dream consolidation",
            "pattern extraction",
            "quality metrics",
            "access patterns",
            "reranker status",
        ],
    },
    {
        "name": "Ingestion",
        "items": [
            "paste ingest",
            "file ingest",
            "JSON ingest",
            "line splitting",
            "paragraph splitting",
            "single-block ingest",
            "batch API ingest",
            "source naming",
            "source type labels",
            "ingest run history",
        ],
    },
    {
        "name": "Operations",
        "items": [
            "service status page",
            "runtime cache stats",
            "workspace health",
            "memory map",
            "layer counts",
            "month counts",
            "source counts",
            "entity counts",
            "recent export",
            "service metadata API",
        ],
    },
    {
        "name": "Workspace control",
        "items": [
            "GitHub login",
            "workspace creation",
            "workspace invites",
            "member records",
            "API key creation",
            "API key revocation",
            "key last-used tracking",
            "audit history",
            "usage route counts",
            "usage event feed",
        ],
    },
    {
        "name": "Public site",
        "items": [
            "home page",
            "docs page",
            "agent page",
            "examples page",
            "security page",
            "status page",
            "changelog page",
            "capabilities page",
            "robots.txt",
            "sitemap.xml",
        ],
    },
    {
        "name": "Deployment",
        "items": [
            "VPS runtime",
            "Dockerfile",
            "docker compose",
            "Postgres metadata",
            "workspace Postgres schemas",
            "warm runtime cache",
            "runtime eviction",
            "Caddy/nginx ready",
            "serverless guidance",
            "proprietary license page",
        ],
    },
    {
        "name": "Discovery APIs",
        "items": [
            "capabilities JSON",
            "MCP manifest JSON",
            "service manifest JSON",
            "tool category groups",
            "recipe discovery",
            "skill discovery",
            "public OpenAPI link",
            "machine-readable counts",
            "public route catalog",
            "agent bootstrap map",
        ],
    },
    {
        "name": "Client UX",
        "items": [
            "capability ledger",
            "tool group sections",
            "copyable curl blocks",
            "environment setup block",
            "recipe playbooks",
            "minimal nav",
            "responsive capability lists",
            "scan-friendly tables",
            "plain language docs",
            "free-service messaging",
        ],
    },
    {
        "name": "Agent safety",
        "items": [
            "workspace-scoped auth",
            "no public memory calls",
            "explicit argument hints",
            "curation tools documented",
            "negative knowledge capture",
            "audit on bridge calls",
            "usage trail on bridge calls",
            "revocable keys",
            "soft-delete memory path",
            "status history lookup",
        ],
    },
    {
        "name": "Operator workflows",
        "items": [
            "health check recipe",
            "curation recipe",
            "entity pivot recipe",
            "checkpoint recipe",
            "compact context recipe",
            "capability sync recipe",
            "tool manifest recipe",
            "usage monitor recipe",
            "ingestion recipe",
            "handoff recipe",
        ],
    },
    {
        "name": "SDK snippets",
        "items": [
            "JavaScript fetch snippet",
            "Python requests snippet",
            "shell recall snippet",
            "agent bootstrap snippet",
            "batch ingest snippet",
            "manifest client snippet",
            "copy buttons",
            "language labels",
            "snippet JSON endpoint",
            "SDK page",
        ],
    },
    {
        "name": "Playbooks",
        "items": [
            "new agent session",
            "repository handoff",
            "memory cleanup",
            "investigation pivot",
            "client onboarding",
            "ordered steps",
            "expected outcomes",
            "operator-facing copy",
            "agent-facing workflow",
            "playbook JSON endpoint",
        ],
    },
    {
        "name": "Observability",
        "items": [
            "route-level usage",
            "key-level usage",
            "event feed",
            "audit feed",
            "runtime cache status",
            "service status JSON",
            "workspace status endpoint",
            "health tool",
            "quality metrics tool",
            "access pattern tool",
        ],
    },
    {
        "name": "Onboarding",
        "items": [
            "environment variables",
            "bootstrap-first flow",
            "tool manifest flow",
            "capability sync flow",
            "copyable examples",
            "free service explanation",
            "GitHub sign-in path",
            "workspace key path",
            "starter skill path",
            "OpenAPI path",
        ],
    },
    {
        "name": "API examples",
        "items": [
            "example catalog page",
            "example JSON endpoint",
            "public route examples",
            "workspace route examples",
            "bridge call examples",
            "ingest examples",
            "usage examples",
            "export examples",
            "auth examples",
            "copyable fixture blocks",
        ],
    },
    {
        "name": "Response fixtures",
        "items": [
            "service status fixture",
            "bootstrap fixture",
            "recall fixture",
            "checkpoint fixture",
            "ingest fixture",
            "usage fixture",
            "MCP manifest fixture",
            "capability fixture",
            "recent export fixture",
            "error shape fixture",
        ],
    },
    {
        "name": "Playground UX",
        "items": [
            "method labels",
            "auth labels",
            "request body preview",
            "response body preview",
            "workspace slug placeholders",
            "environment assumptions",
            "API explorer nav item",
            "docs cross-link",
            "examples cross-link",
            "client implementation guide",
        ],
    },
    {
        "name": "Connection kits",
        "items": [
            "workspace connect page",
            "workspace config JSON",
            ".env template endpoint",
            "agent startup sequence",
            "bootstrap command",
            "recent memory command",
            "checkpoint command",
            "ingest command",
            "health check command",
            "copyable connection blocks",
        ],
    },
    {
        "name": "Agent configs",
        "items": [
            "service identity",
            "workspace identity",
            "base URL",
            "workspace slug",
            "auth header names",
            "endpoint map",
            "MCP transport",
            "tool discovery URL",
            "starter skill URLs",
            "recommended first calls",
        ],
    },
]


API_EXAMPLES = [
    {
        "name": "Service status",
        "method": "GET",
        "path": "/api/service/status",
        "auth": "public",
        "summary": "Check whether the hosted service is alive and read public counts.",
        "request": None,
        "response": {
            "status": "ok",
            "service": "memorylayer",
            "runtime": "vps",
            "database": "postgres",
            "features": 29,
            "capabilities": 230,
            "mcp_tools": 60,
        },
    },
    {
        "name": "Service manifest",
        "method": "GET",
        "path": "/api/service/manifest",
        "auth": "public",
        "summary": "Load the route map and public integration counts for client setup screens.",
        "request": None,
        "response": {
            "service": "memorylayer",
            "routes": {
                "docs": "https://memorylayer.run/docs",
                "api_examples": "https://memorylayer.run/api/examples",
                "mcp_manifest": "https://memorylayer.run/api/mcp/manifest",
            },
            "counts": {"capabilities": 250, "api_examples": 12},
        },
    },
    {
        "name": "MCP manifest",
        "method": "GET",
        "path": "/api/mcp/manifest",
        "auth": "public",
        "summary": "Discover grouped tools, auth headers, and workspace bridge URL templates.",
        "request": None,
        "response": {
            "transport": "http-json",
            "workspace_call_url_template": "https://memorylayer.run/api/workspaces/{slug}/mcp",
            "auth": ["Authorization: Bearer <workspace-api-key>", "X-API-Key: <workspace-api-key>"],
            "tool_groups": [{"name": "Retrieval", "tools": [{"name": "recall_context"}]}],
        },
    },
    {
        "name": "Workspace bootstrap",
        "method": "GET",
        "path": "/api/workspaces/{slug}/bootstrap",
        "auth": "workspace key",
        "summary": "Fetch workspace-specific URLs, headers, starter skills, and tool discovery.",
        "request": None,
        "response": {
            "workspace": {"slug": "demo"},
            "auth": {"headers": ["Authorization: Bearer <workspace-api-key>", "X-API-Key: <workspace-api-key>"]},
            "endpoints": {"mcp": "https://memorylayer.run/api/workspaces/demo/mcp"},
            "skills": [{"name": "workspace-memory"}],
        },
    },
    {
        "name": "Connection kit",
        "method": "GET",
        "path": "/api/workspaces/{slug}/connect",
        "auth": "workspace key",
        "summary": "Return a normalized client profile with endpoints, MCP config, skills, and startup calls.",
        "request": None,
        "response": {
            "service": {"name": "Memorylayer", "base_url": "https://memorylayer.run"},
            "workspace": {"slug": "demo"},
            "endpoints": {"mcp": "https://memorylayer.run/api/workspaces/demo/mcp"},
            "startup_calls": [{"name": "bootstrap", "method": "GET"}],
        },
    },
    {
        "name": "Env template",
        "method": "GET",
        "path": "/api/workspaces/{slug}/env",
        "auth": "workspace key",
        "summary": "Return a plain text env block for local scripts, workers, and agent launchers.",
        "request": None,
        "response": {
            "text": "MEMORYLAYER_URL=\"https://memorylayer.run\"\nMEMORYLAYER_WORKSPACE=\"demo\"\nMEMORYLAYER_KEY=\"engram_...\""
        },
    },
    {
        "name": "Recall context",
        "method": "POST",
        "path": "/api/workspaces/{slug}/mcp",
        "auth": "workspace key",
        "summary": "Ask the bridge for compact context before an agent starts work.",
        "request": {"tool": "recall_context", "args": {"query": "current project state", "max_tokens": 1200}},
        "response": {"ok": True, "tool": "recall_context", "result": "Relevant memory context..."},
    },
    {
        "name": "Session checkpoint",
        "method": "POST",
        "path": "/api/workspaces/{slug}/mcp",
        "auth": "workspace key",
        "summary": "Save a compact handoff after meaningful work or deployment.",
        "request": {"tool": "session_checkpoint", "args": {"note": "Shipped API explorer", "limit": 8}},
        "response": {"ok": True, "tool": "session_checkpoint", "result": {"saved": True}},
    },
    {
        "name": "Batch ingest",
        "method": "POST",
        "path": "/api/workspaces/{slug}/ingest",
        "auth": "workspace key",
        "summary": "Import notes, transcripts, reports, or pipeline output as memories.",
        "request": {
            "source_name": "handoff.md",
            "source_type": "handoff",
            "items": ["Release deployed", "Next: test onboarding"],
            "memory_type": "fact",
        },
        "response": {"ok": True, "run": {"source_name": "handoff.md", "items": 2}, "memory_ids": ["mem_1", "mem_2"]},
    },
    {
        "name": "Usage feed",
        "method": "GET",
        "path": "/api/workspaces/{slug}/usage",
        "auth": "workspace key",
        "summary": "Read recent API calls, per-route totals, and key activity.",
        "request": None,
        "response": {
            "route_counts": [{"route": "/api/workspaces/demo/mcp", "count": 14}],
            "recent_events": [{"route": "/api/workspaces/demo/mcp", "status_code": 200}],
        },
    },
    {
        "name": "Recent export",
        "method": "GET",
        "path": "/api/workspaces/{slug}/export/recent",
        "auth": "workspace key",
        "summary": "Export the latest workspace memories for backup, inspection, or migration checks.",
        "request": None,
        "response": {
            "workspace": "demo",
            "memories": [{"content": "API explorer deployed", "memory_type": "fact", "layer": "episodic"}],
        },
    },
    {
        "name": "Error shape",
        "method": "POST",
        "path": "/api/workspaces/{slug}/mcp",
        "auth": "workspace key",
        "summary": "All service errors return a direct detail message that clients can show or log.",
        "request": {"tool": "unknown_tool", "args": {}},
        "response": {"detail": "Unsupported tool: unknown_tool"},
    },
]


def capability_count() -> int:
    return sum(len(group["items"]) for group in CAPABILITY_GROUPS)


def public_manifest() -> dict:
    return {
        "service": "memorylayer",
        "name": "Memorylayer",
        "runtime": "vps",
        "database": "postgres",
        "base_url": settings.base_url,
        "routes": {
            "home": f"{settings.base_url}/",
            "docs": f"{settings.base_url}/docs",
            "agents": f"{settings.base_url}/agents",
            "connect": f"{settings.base_url}/connect",
            "capabilities": f"{settings.base_url}/capabilities",
            "examples": f"{settings.base_url}/examples",
            "api_explorer": f"{settings.base_url}/api-explorer",
            "sdks": f"{settings.base_url}/sdks",
            "status": f"{settings.base_url}/status",
            "openapi": f"{settings.base_url}/openapi.json",
            "service_status": f"{settings.base_url}/api/service/status",
            "capabilities_json": f"{settings.base_url}/api/capabilities",
            "mcp_manifest": f"{settings.base_url}/api/mcp/manifest",
            "sdk_snippets": f"{settings.base_url}/api/sdk-snippets",
            "playbooks": f"{settings.base_url}/api/playbooks",
            "api_examples": f"{settings.base_url}/api/examples",
        },
        "counts": {
            "features": len(SERVICE_FEATURES),
            "capabilities": capability_count(),
            "mcp_tools": len(SUPPORTED_TOOLS),
            "tool_groups": len(grouped_tool_list()),
            "recipes": len(INTEGRATION_RECIPES),
            "sdk_snippets": len(SDK_SNIPPETS),
            "playbooks": len(PLAYBOOKS),
            "api_examples": len(API_EXAMPLES),
            "skills": len(STARTER_SKILLS),
        },
    }


CHANGELOG_ENTRIES = [
    {
        "version": "Security hardening",
        "date": "2026-04-24",
        "changes": [
            "Added global security headers: CSP, frame blocking, nosniff, referrer policy, permissions policy, and HSTS on HTTPS.",
            "Added host allow-list enforcement, browser origin checks for state-changing workspace routes, and request body size limits.",
            "Hardened session cookie settings with a dedicated cookie name, SameSite=Lax, configurable HTTPS-only cookies, and a bounded session lifetime.",
            "Added basic auth/API throttles plus input bounds for workspace names, queries, memory content, ingest payloads, labels, roles, and API limits.",
            "Expanded security tests to cover headers, bad hosts, and cross-origin form blocking.",
        ],
    },
    {
        "version": "Editorial visual reset",
        "date": "2026-04-24",
        "changes": [
            "Replaced the glow-heavy dark treatment with a calmer editorial product system: ivory surface, black ink, restrained borders, and less decorative noise.",
            "Reworked the shared navigation, hero, badges, forms, code blocks, and diagram panels so inherited pages feel more deliberate.",
            "Tightened the homepage headline and connection-kit positioning around concrete hosted-memory infrastructure.",
            "Kept the service free positioning while making the public site look closer to a serious developer product.",
        ],
    },
    {
        "version": "Cloud host",
        "date": "2026-04-24",
        "changes": [
            "Added workspace paste, file, and batch API ingestion.",
            "Added ingestion run history and recent memory export.",
            "Added structured API usage tracking per workspace key.",
            "Added hosted usage endpoint and dashboard activity stream.",
            "Redesigned the public site around a cleaner infrastructure-style shell.",
            "Added hosted MCP bridge, bootstrap payloads, and downloadable starter skills.",
        ],
    },
    {
        "version": "Initial service",
        "date": "2026-04-23",
        "changes": [
            "Added GitHub login, workspace provisioning, invites, and API keys.",
            "Provisioned one Engram schema per workspace.",
            "Deployed Memorylayer to the VPS at memorylayer.run.",
        ],
    },
]


def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def render(request: Request, template: str, **context):
    return templates.TemplateResponse(request, template, {
        "request": request,
        "settings": settings,
        "current_user_id": current_user_id(request),
        "flash": pop_flash(request),
        **context,
    })


def set_flash(request: Request, kind: str, message: str) -> None:
    request.session["_flash"] = {"kind": kind, "message": message}


def pop_flash(request: Request) -> dict | None:
    return request.session.pop("_flash", None)


def user_display_name(user: User | None) -> str:
    if not user:
        return "system"
    return user.name or user.login


def record_audit_event(
    db,
    workspace_id: str,
    event_type: str,
    summary: str,
    actor_user_id: str | None = None,
    metadata: dict | None = None,
) -> None:
    db.add(
        AuditEvent(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            event_type=event_type,
            summary=summary,
            metadata_json=json.dumps(metadata or {}),
        )
    )


def record_api_event(
    db,
    workspace_id: str,
    api_key_id: str | None,
    route: str,
    method: str = "GET",
    status_code: int = 200,
    metadata: dict | None = None,
) -> None:
    db.add(
        WorkspaceApiEvent(
            workspace_id=workspace_id,
            api_key_id=api_key_id,
            route=route,
            method=method,
            status_code=status_code,
            metadata_json=json.dumps(metadata or {}),
        )
    )


def normalize_layer(value: str | None) -> str:
    return value if value in {"working", "episodic", "semantic", "procedural"} else "episodic"


def normalize_memory_type(value: str | None) -> str:
    return value if value in {"narrative", "fact", "procedure"} else "narrative"


def bounded_text(value: str, field_name: str, max_chars: int) -> str:
    cleaned = value.strip()
    if len(cleaned) > max_chars:
        raise HTTPException(status_code=400, detail=f"{field_name} is limited to {max_chars} characters")
    return cleaned


def bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def split_ingest_text(raw_text: str, mode: str = "auto", max_items: int = 80) -> list[str]:
    text = raw_text.replace("\r\n", "\n").strip()
    if not text:
        return []
    if mode == "single":
        return [text]
    if mode == "lines":
        chunks = [line.strip("- \t") for line in text.splitlines() if line.strip("- \t")]
    elif mode == "paragraphs":
        chunks = [part.strip() for part in text.split("\n\n") if part.strip()]
    elif mode == "json":
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="Invalid JSON ingest payload") from exc
        if isinstance(parsed, list):
            chunks = [json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item for item in parsed]
        elif isinstance(parsed, dict):
            chunks = [
                json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item
                for item in parsed.get("items", parsed.get("memories", [parsed]))
            ]
        else:
            chunks = [str(parsed)]
    else:
        if "\n\n" in text:
            chunks = [part.strip() for part in text.split("\n\n") if part.strip()]
        else:
            chunks = [line.strip("- \t") for line in text.splitlines() if line.strip("- \t")]
        if len(chunks) <= 1 and len(text) > 1800:
            chunks = [text[index : index + 1400].strip() for index in range(0, len(text), 1400)]
    return [chunk for chunk in chunks if chunk][:max_items]


def ingest_workspace_items(
    db,
    workspace: Workspace,
    items: list[str],
    source_name: str,
    source_type: str,
    layer: str,
    memory_type: str,
    actor_user_id: str | None = None,
    api_key_id: str | None = None,
    metadata: dict | None = None,
) -> WorkspaceIngestRun:
    clean_items = [item.strip() for item in items if item and item.strip()]
    if not clean_items:
        raise HTTPException(status_code=400, detail="No ingestable content found")
    if len(clean_items) > 100:
        raise HTTPException(status_code=400, detail="Ingestion is limited to 100 items per request")
    for item in clean_items:
        workspace_remember(workspace.schema_name, content=item, layer=layer, memory_type=memory_type)
    run = WorkspaceIngestRun(
        workspace_id=workspace.id,
        actor_user_id=actor_user_id,
        api_key_id=api_key_id,
        source_name=source_name[:180] or "manual import",
        source_type=source_type[:80] or "text",
        layer=layer,
        memory_type=memory_type,
        item_count=len(clean_items),
        character_count=sum(len(item) for item in clean_items),
        metadata_json=json.dumps(metadata or {}),
    )
    db.add(run)
    return run


def require_workspace_role(membership: WorkspaceMember, allowed_roles: set[str]) -> None:
    if membership.role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient workspace role")


def _load_membership_for_user(db, user_id: str, slug: str) -> tuple[Workspace, WorkspaceMember]:
    ws = db.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")
    membership = db.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == ws.id,
            WorkspaceMember.user_id == user_id,
        )
    ).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="No access to this workspace")
    return ws, membership


def _workspace_people(db, workspace_id: str) -> list[dict]:
    rows = db.execute(
        select(WorkspaceMember, User)
        .join(User, User.id == WorkspaceMember.user_id)
        .where(WorkspaceMember.workspace_id == workspace_id)
        .order_by(WorkspaceMember.created_at.asc())
    ).all()
    return [
        {
            "membership_id": membership.id,
            "role": membership.role,
            "login": user.login,
            "name": user.name,
            "avatar_url": user.avatar_url,
            "joined_at": membership.created_at,
        }
        for membership, user in rows
    ]


def _workspace_invites(db, workspace_id: str) -> list[WorkspaceInvite]:
    return db.execute(
        select(WorkspaceInvite)
        .where(WorkspaceInvite.workspace_id == workspace_id)
        .order_by(WorkspaceInvite.created_at.desc())
    ).scalars().all()


def _workspace_api_keys(db, workspace_id: str) -> list[WorkspaceApiKey]:
    return db.execute(
        select(WorkspaceApiKey)
        .where(WorkspaceApiKey.workspace_id == workspace_id)
        .order_by(WorkspaceApiKey.created_at.desc())
    ).scalars().all()


def _workspace_audit_feed(db, workspace_id: str, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(AuditEvent, User)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(AuditEvent.workspace_id == workspace_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "event_type": event.event_type,
            "summary": event.summary,
            "actor": user_display_name(user),
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "metadata": json.loads(event.metadata_json or "{}"),
        }
        for event, user in rows
    ]


def _workspace_api_usage_feed(db, workspace_id: str, limit: int = 20) -> list[dict]:
    rows = db.execute(
        select(WorkspaceApiEvent, WorkspaceApiKey)
        .outerjoin(WorkspaceApiKey, WorkspaceApiKey.id == WorkspaceApiEvent.api_key_id)
        .where(WorkspaceApiEvent.workspace_id == workspace_id)
        .order_by(WorkspaceApiEvent.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "route": event.route,
            "method": event.method,
            "status_code": event.status_code,
            "created_at": event.created_at.isoformat() if event.created_at else None,
            "api_key_label": api_key.label if api_key else "unknown key",
            "api_key_prefix": api_key.token_prefix if api_key else "",
            "metadata": json.loads(event.metadata_json or "{}"),
        }
        for event, api_key in rows
    ]


def _workspace_api_usage_summary(db, workspace_id: str) -> dict:
    total = db.execute(
        select(func.count()).select_from(WorkspaceApiEvent).where(WorkspaceApiEvent.workspace_id == workspace_id)
    ).scalar_one()
    last_seen = db.execute(
        select(func.max(WorkspaceApiEvent.created_at)).where(WorkspaceApiEvent.workspace_id == workspace_id)
    ).scalar_one()
    route_rows = db.execute(
        select(WorkspaceApiEvent.route, func.count())
        .where(WorkspaceApiEvent.workspace_id == workspace_id)
        .group_by(WorkspaceApiEvent.route)
        .order_by(func.count().desc())
        .limit(8)
    ).all()
    key_rows = db.execute(
        select(WorkspaceApiKey.id, func.count(WorkspaceApiEvent.id))
        .outerjoin(WorkspaceApiEvent, WorkspaceApiEvent.api_key_id == WorkspaceApiKey.id)
        .where(WorkspaceApiKey.workspace_id == workspace_id)
        .group_by(WorkspaceApiKey.id)
    ).all()
    return {
        "total_calls": total or 0,
        "last_seen": last_seen.isoformat() if last_seen else None,
        "top_routes": [{"route": route, "calls": calls} for route, calls in route_rows],
        "key_calls": {key_id: calls for key_id, calls in key_rows},
    }


def _workspace_ingest_runs(db, workspace_id: str, limit: int = 12) -> list[dict]:
    rows = db.execute(
        select(WorkspaceIngestRun, User, WorkspaceApiKey)
        .outerjoin(User, User.id == WorkspaceIngestRun.actor_user_id)
        .outerjoin(WorkspaceApiKey, WorkspaceApiKey.id == WorkspaceIngestRun.api_key_id)
        .where(WorkspaceIngestRun.workspace_id == workspace_id)
        .order_by(WorkspaceIngestRun.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "source_name": run.source_name,
            "source_type": run.source_type,
            "layer": run.layer,
            "memory_type": run.memory_type,
            "item_count": run.item_count,
            "character_count": run.character_count,
            "status": run.status,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "actor": user_display_name(user) if user else (api_key.label if api_key else "api"),
            "metadata": json.loads(run.metadata_json or "{}"),
        }
        for run, user, api_key in rows
    ]


def _workspace_operator_summary(db, workspace_id: str) -> dict:
    active_keys = db.execute(
        select(func.count())
        .select_from(WorkspaceApiKey)
        .where(WorkspaceApiKey.workspace_id == workspace_id, WorkspaceApiKey.revoked_at.is_(None))
    ).scalar_one()
    open_invites = db.execute(
        select(func.count())
        .select_from(WorkspaceInvite)
        .where(
            WorkspaceInvite.workspace_id == workspace_id,
            WorkspaceInvite.accepted_at.is_(None),
            WorkspaceInvite.revoked_at.is_(None),
        )
    ).scalar_one()
    ingest_total = db.execute(
        select(func.count()).select_from(WorkspaceIngestRun).where(WorkspaceIngestRun.workspace_id == workspace_id)
    ).scalar_one()
    ingested_items = db.execute(
        select(func.coalesce(func.sum(WorkspaceIngestRun.item_count), 0)).where(WorkspaceIngestRun.workspace_id == workspace_id)
    ).scalar_one()
    return {
        "active_keys": active_keys or 0,
        "open_invites": open_invites or 0,
        "ingest_runs": ingest_total or 0,
        "ingested_items": ingested_items or 0,
    }


def _workspace_view_context(db, workspace: Workspace, search_results=None, search_query: str = "", revealed_api_key: str | None = None):
    api_usage_summary = _workspace_api_usage_summary(db, workspace.id)
    return {
        "workspace": workspace,
        "stats": workspace_status(workspace.schema_name),
        "recent": workspace_recent_memories(workspace.schema_name, limit=12),
        "search_results": search_results,
        "search_query": search_query,
        "members": _workspace_people(db, workspace.id),
        "invites": _workspace_invites(db, workspace.id),
        "api_keys": _workspace_api_keys(db, workspace.id),
        "audit_events": _workspace_audit_feed(db, workspace.id),
        "api_usage_events": _workspace_api_usage_feed(db, workspace.id),
        "api_usage_summary": api_usage_summary,
        "ingest_runs": _workspace_ingest_runs(db, workspace.id),
        "operator_summary": _workspace_operator_summary(db, workspace.id),
        "revealed_api_key": revealed_api_key,
        "connection_kit": workspace_connection_kit(workspace, api_key_label="workspace key"),
    }


def workspace_endpoint_map(workspace: Workspace) -> dict:
    base = f"{settings.base_url}/api/workspaces/{workspace.slug}"
    return {
        "bootstrap": f"{base}/bootstrap",
        "status": f"{base}/status",
        "recent": f"{base}/memories/recent",
        "search": f"{base}/search",
        "remember": f"{base}/remember",
        "ingest": f"{base}/ingest",
        "ingest_runs": f"{base}/ingest/runs",
        "export_recent": f"{base}/export/recent",
        "usage": f"{base}/usage",
        "audit": f"{base}/audit",
        "mcp": f"{base}/mcp",
        "mcp_tools": f"{base}/mcp/tools",
    }


def workspace_connection_kit(workspace: Workspace, api_key_label: str = "workspace key", token_hint: str = "engram_...") -> dict:
    endpoints = workspace_endpoint_map(workspace)
    return {
        "service": {
            "name": "Memorylayer",
            "base_url": settings.base_url,
            "docs_url": f"{settings.base_url}/docs",
            "connect_url": f"{settings.base_url}/connect",
            "openapi_url": f"{settings.base_url}/openapi.json",
        },
        "workspace": {
            "name": workspace.name,
            "slug": workspace.slug,
            "schema_name": workspace.schema_name,
        },
        "auth": {
            "api_key_label": api_key_label,
            "headers": ["Authorization: Bearer <workspace-api-key>", "X-API-Key: <workspace-api-key>"],
            "token_hint": token_hint,
        },
        "endpoints": endpoints,
        "mcp": {
            "transport": "http-json",
            "call_url": endpoints["mcp"],
            "tools_url": endpoints["mcp_tools"],
            "manifest_url": f"{settings.base_url}/api/mcp/manifest",
        },
        "skills": [
            {
                "name": skill["name"],
                "title": skill["title"],
                "json_url": f"{settings.base_url}/api/skills/{skill['name']}",
                "markdown_url": f"{settings.base_url}/api/skills/{skill['name']}.md",
            }
            for skill in starter_skill_list()
        ],
        "startup_calls": [
            {"name": "bootstrap", "method": "GET", "url": endpoints["bootstrap"]},
            {"name": "recent memory", "method": "GET", "url": f"{endpoints['recent']}?limit=8"},
            {"name": "tool discovery", "method": "GET", "url": endpoints["mcp_tools"]},
            {
                "name": "compact context",
                "method": "POST",
                "url": endpoints["mcp"],
                "body": {"tool": "recall_context", "args": {"query": "current task", "max_tokens": 1200}},
            },
        ],
        "env": {
            "MEMORYLAYER_URL": settings.base_url,
            "MEMORYLAYER_WORKSPACE": workspace.slug,
            "MEMORYLAYER_KEY": token_hint,
            "MEMORYLAYER_MCP_URL": endpoints["mcp"],
        },
    }


def render_workspace_env(workspace: Workspace, token_hint: str = "engram_...") -> str:
    kit = workspace_connection_kit(workspace, token_hint=token_hint)
    return "\n".join(f'{key}="{value}"' for key, value in kit["env"].items()) + "\n"


def api_key_from_request(authorization: str | None, x_api_key: str | None) -> str | None:
    if x_api_key:
        return x_api_key.strip()[:512]
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()[:512]
    return None


def require_api_workspace(db, slug: str, authorization: str | None, x_api_key: str | None):
    token = api_key_from_request(authorization, x_api_key)
    if not token:
        raise HTTPException(status_code=401, detail="Missing API key")
    api_key = resolve_api_workspace(db, slug, token)
    workspace = db.execute(select(Workspace).where(Workspace.id == api_key.workspace_id)).scalar_one()
    return workspace, api_key


def resolve_api_workspace(db, slug: str, token: str) -> WorkspaceApiKey:
    token_hash = digest_token(token)
    api_key = db.execute(
        select(WorkspaceApiKey)
        .join(Workspace, Workspace.id == WorkspaceApiKey.workspace_id)
        .where(
            Workspace.slug == slug,
            WorkspaceApiKey.token_hash == token_hash,
            WorkspaceApiKey.revoked_at.is_(None),
        )
    ).scalar_one_or_none()
    if not api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    api_key.last_used_at = utc_now()
    db.commit()
    return api_key


def safe_workspace_snapshot(schema_name: str, recent_limit: int = 4) -> tuple[dict, list[dict], str | None]:
    try:
        return workspace_status(schema_name), workspace_recent_memories(schema_name, limit=recent_limit), None
    except Exception as exc:
        return (
            {"memories": {"total": 0}, "entities": 0, "relationships": 0},
            [],
            str(exc),
        )


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    if current_user_id(request):
        return RedirectResponse("/app", status_code=302)
    return render(
        request,
        "landing.html",
        features=SERVICE_FEATURES,
        recipes=INTEGRATION_RECIPES,
        tools=SUPPORTED_TOOLS,
        tool_groups=grouped_tool_list(),
        capability_groups=CAPABILITY_GROUPS,
        capability_count=capability_count(),
        sdk_snippets=SDK_SNIPPETS,
        playbooks=PLAYBOOKS,
        api_examples=API_EXAMPLES,
    )


@app.get("/agents", response_class=HTMLResponse)
async def agents_page(request: Request):
    return render(
        request,
        "agents.html",
        skills=starter_skill_list(),
        recipes=INTEGRATION_RECIPES,
        tools=SUPPORTED_TOOLS,
        tool_groups=grouped_tool_list(),
        capability_groups=CAPABILITY_GROUPS,
        capability_count=capability_count(),
        sdk_snippets=SDK_SNIPPETS,
        playbooks=PLAYBOOKS,
        api_examples=API_EXAMPLES,
    )


@app.get("/connect", response_class=HTMLResponse)
async def connect_page(request: Request):
    return render(
        request,
        "connect.html",
        tools=SUPPORTED_TOOLS,
        tool_groups=grouped_tool_list(),
        skills=starter_skill_list(),
        openapi_url=f"{settings.base_url}/openapi.json",
    )


@app.get("/pricing")
async def pricing_page():
    return RedirectResponse("/docs", status_code=302)


@app.get("/docs", response_class=HTMLResponse)
async def docs_page(request: Request):
    return render(
        request,
        "docs.html",
        skills=starter_skill_list(),
        tools=SUPPORTED_TOOLS,
        tool_groups=grouped_tool_list(),
        features=SERVICE_FEATURES,
        recipes=INTEGRATION_RECIPES,
        capability_groups=CAPABILITY_GROUPS,
        capability_count=capability_count(),
        sdk_snippets=SDK_SNIPPETS,
        playbooks=PLAYBOOKS,
        api_examples=API_EXAMPLES,
        openapi_url=f"{settings.base_url}/openapi.json",
    )


@app.get("/capabilities", response_class=HTMLResponse)
async def capabilities_page(request: Request):
    return render(
        request,
        "capabilities.html",
        tools=SUPPORTED_TOOLS,
        tool_groups=grouped_tool_list(),
        features=SERVICE_FEATURES,
        capability_groups=CAPABILITY_GROUPS,
        capability_count=capability_count(),
        sdk_snippets=SDK_SNIPPETS,
        playbooks=PLAYBOOKS,
        api_examples=API_EXAMPLES,
    )


@app.get("/security", response_class=HTMLResponse)
async def security_page(request: Request):
    return render(request, "security.html")


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    return render(request, "status.html", features=SERVICE_FEATURES)


@app.get("/examples", response_class=HTMLResponse)
async def examples_page(request: Request):
    return render(
        request,
        "examples.html",
        recipes=INTEGRATION_RECIPES,
        manifest=public_manifest(),
        api_examples=API_EXAMPLES,
    )


@app.get("/api-explorer", response_class=HTMLResponse)
async def api_explorer_page(request: Request):
    return render(
        request,
        "api_explorer.html",
        examples=API_EXAMPLES,
        manifest=public_manifest(),
        openapi_url=f"{settings.base_url}/openapi.json",
    )


@app.get("/sdks", response_class=HTMLResponse)
async def sdks_page(request: Request):
    return render(
        request,
        "sdks.html",
        snippets=SDK_SNIPPETS,
        playbooks=PLAYBOOKS,
        manifest=public_manifest(),
    )


@app.get("/changelog", response_class=HTMLResponse)
async def changelog_page(request: Request):
    return render(request, "changelog.html", entries=CHANGELOG_ENTRIES)


@app.get("/api/service/status")
async def api_service_status():
    return JSONResponse(
        {
            "status": "ok",
            "service": "memorylayer",
            "runtime": "vps",
            "database": "postgres",
            "features": len(SERVICE_FEATURES),
            "capabilities": capability_count(),
            "mcp_tools": len(SUPPORTED_TOOLS),
            "tool_groups": len(grouped_tool_list()),
            "recipes": len(INTEGRATION_RECIPES),
            "sdk_snippets": len(SDK_SNIPPETS),
            "playbooks": len(PLAYBOOKS),
            "api_examples": len(API_EXAMPLES),
            "base_url": settings.base_url,
            "runtime_cache": workspace_runtime_stats(),
        }
    )


@app.get("/api/service/manifest")
async def api_service_manifest():
    return JSONResponse(public_manifest())


@app.get("/api/capabilities")
async def api_capabilities():
    return JSONResponse(
        {
            **public_manifest(),
            "capability_groups": CAPABILITY_GROUPS,
            "features": SERVICE_FEATURES,
            "recipes": INTEGRATION_RECIPES,
            "sdk_snippets": SDK_SNIPPETS,
            "playbooks": PLAYBOOKS,
            "api_examples": API_EXAMPLES,
        }
    )


@app.get("/api/sdk-snippets")
async def api_sdk_snippets():
    return JSONResponse({**public_manifest(), "sdk_snippets": SDK_SNIPPETS})


@app.get("/api/playbooks")
async def api_playbooks():
    return JSONResponse({**public_manifest(), "playbooks": PLAYBOOKS})


@app.get("/api/examples")
async def api_examples():
    return JSONResponse({**public_manifest(), "api_examples": API_EXAMPLES})


@app.get("/api/mcp/manifest")
async def api_mcp_manifest():
    return JSONResponse(
        {
            **public_manifest(),
            "transport": "http-json",
            "workspace_call_url_template": f"{settings.base_url}/api/workspaces/{{slug}}/mcp",
            "workspace_tools_url_template": f"{settings.base_url}/api/workspaces/{{slug}}/mcp/tools",
            "auth": ["Authorization: Bearer <workspace-api-key>", "X-API-Key: <workspace-api-key>"],
            "tool_groups": grouped_tool_list(),
            "tools": SUPPORTED_TOOLS,
        }
    )


@app.get("/robots.txt")
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\nAllow: /\nSitemap: " + f"{settings.base_url}/sitemap.xml\n",
        media_type="text/plain; charset=utf-8",
    )


@app.get("/sitemap.xml")
async def sitemap_xml():
    routes = [
        "",
        "agents",
        "connect",
        "docs",
        "capabilities",
        "examples",
        "api-explorer",
        "sdks",
        "security",
        "status",
        "changelog",
        "login",
        "api/service/manifest",
        "api/capabilities",
        "api/mcp/manifest",
        "api/sdk-snippets",
        "api/playbooks",
        "api/examples",
    ]
    body = "\n".join(
        f"  <url><loc>{settings.base_url}/{route}</loc></url>" if route else f"  <url><loc>{settings.base_url}/</loc></url>"
        for route in routes
    )
    return Response(
        f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<urlset xmlns=\"http://www.sitemaps.org/schemas/sitemap/0.9\">\n{body}\n</urlset>\n",
        media_type="application/xml",
    )


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return render(request, "login.html")


@app.get("/login/github")
async def login_github(request: Request):
    redirect_uri = f"{settings.base_url}/auth/github/callback"
    return await oauth.github.authorize_redirect(request, redirect_uri)


@app.get("/auth/github/callback")
async def github_callback(request: Request):
    token = await oauth.github.authorize_access_token(request)
    profile = await oauth.github.get("user", token=token)
    user_data = profile.json()

    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.github_id == str(user_data["id"]))).scalar_one_or_none()
        if not user:
            user = User(
                github_id=str(user_data["id"]),
                login=user_data["login"],
                name=user_data.get("name"),
                avatar_url=user_data.get("avatar_url"),
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.login = user_data["login"]
            user.name = user_data.get("name")
            user.avatar_url = user_data.get("avatar_url")
            db.commit()
        request.session["user_id"] = user.id
    finally:
        db.close()

    return RedirectResponse("/app", status_code=302)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=302)


@app.get("/app", response_class=HTMLResponse)
@login_required
async def dashboard(request: Request):
    user_id = current_user_id(request)
    db = SessionLocal()
    try:
        memberships = db.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        ).scalars().all()
        workspace_ids = [m.workspace_id for m in memberships]
        workspaces = db.execute(
            select(Workspace).where(Workspace.id.in_(workspace_ids)) if workspace_ids else select(Workspace).where(false())
        ).scalars().all()
        enriched = []
        for ws in workspaces:
            stats, recent, health_error = safe_workspace_snapshot(ws.schema_name, recent_limit=4)
            enriched.append({
                "workspace": ws,
                "stats": stats,
                "recent": recent,
                "health_error": health_error,
                "member_count": db.execute(
                    select(func.count()).select_from(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id)
                ).scalar_one(),
            })
        return render(request, "dashboard.html", workspaces=enriched)
    finally:
        db.close()


@app.post("/app/workspaces")
@login_required
async def create_workspace(request: Request, name: str = Form(...)):
    user_id = current_user_id(request)
    name = bounded_text(name, "workspace name", 80)
    slug = slugify(name)
    schema_name = schema_name_for_slug(slug)
    db = SessionLocal()
    try:
        exists = db.execute(select(Workspace).where(Workspace.slug == slug)).scalar_one_or_none()
        if exists:
            raise HTTPException(status_code=400, detail="Workspace slug already exists")
        ws = Workspace(name=name.strip(), slug=slug, schema_name=schema_name, owner_id=user_id)
        db.add(ws)
        db.commit()
        db.refresh(ws)
        db.add(WorkspaceMember(workspace_id=ws.id, user_id=user_id, role="owner"))
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="workspace.created",
            summary=f"Created workspace {ws.name}",
            metadata={"slug": ws.slug, "schema_name": ws.schema_name},
        )
        db.commit()
        try:
            init_workspace_store(schema_name)
        except Exception:
            db.execute(delete(WorkspaceMember).where(WorkspaceMember.workspace_id == ws.id))
            db.execute(delete(AuditEvent).where(AuditEvent.workspace_id == ws.id))
            db.execute(delete(Workspace).where(Workspace.id == ws.id))
            db.commit()
            raise
        set_flash(request, "success", f"{ws.name} is ready.")
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "engram-cloud"}


@app.get("/app/workspaces/{slug}", response_class=HTMLResponse)
@login_required
async def workspace_page(request: Request, slug: str):
    user_id = current_user_id(request)
    db = SessionLocal()
    try:
        ws, _membership = _load_membership_for_user(db, user_id, slug)
        return render(request, "workspace.html", **_workspace_view_context(db, ws))
    finally:
        db.close()


@app.post("/app/workspaces/{slug}/search", response_class=HTMLResponse)
@login_required
async def workspace_search_view(request: Request, slug: str, query: str = Form(...)):
    user_id = current_user_id(request)
    query = bounded_text(query, "query", 500)
    db = SessionLocal()
    try:
        ws, _membership = _load_membership_for_user(db, user_id, slug)
        return render(
            request,
            "workspace.html",
            **_workspace_view_context(
                db,
                ws,
                search_results=workspace_search(ws.schema_name, query=query, top_k=10),
                search_query=query,
            ),
        )
    finally:
        db.close()


@app.post("/app/workspaces/{slug}/remember")
@login_required
async def workspace_remember_view(
    request: Request,
    slug: str,
    content: str = Form(...),
    layer: str = Form("episodic"),
    memory_type: str = Form("narrative"),
):
    user_id = current_user_id(request)
    content = bounded_text(content, "content", 20_000)
    db = SessionLocal()
    try:
        ws, membership = _load_membership_for_user(db, user_id, slug)
        require_workspace_role(membership, {"owner", "admin", "editor"})
        workspace_remember(ws.schema_name, content=content, layer=layer, memory_type=memory_type)
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="memory.remembered",
            summary=f"Stored a {memory_type} memory in {layer}",
            metadata={"layer": layer, "memory_type": memory_type, "preview": content[:180]},
        )
        db.commit()
        set_flash(request, "success", "Memory stored.")
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.post("/app/workspaces/{slug}/ingest")
@login_required
async def workspace_ingest_view(
    request: Request,
    slug: str,
    source_name: str = Form("manual import"),
    source_type: str = Form("text"),
    ingest_text: str = Form(""),
    split_mode: str = Form("auto"),
    layer: str = Form("episodic"),
    memory_type: str = Form("narrative"),
    upload: UploadFile | None = File(default=None),
):
    user_id = current_user_id(request)
    source_name = bounded_text(source_name, "source_name", 180)
    source_type = bounded_text(source_type, "source_type", 80)
    ingest_text = bounded_text(ingest_text, "ingest_text", 200_000)
    db = SessionLocal()
    try:
        ws, membership = _load_membership_for_user(db, user_id, slug)
        require_workspace_role(membership, {"owner", "admin", "editor"})
        file_text = ""
        file_name = ""
        if upload and upload.filename:
            file_name = bounded_text(upload.filename, "filename", 180)
            file_text = bounded_text((await upload.read()).decode("utf-8", errors="replace"), "uploaded file", 200_000)
        raw_text = "\n\n".join(part for part in [ingest_text.strip(), file_text.strip()] if part)
        chunks = split_ingest_text(raw_text, mode=split_mode)
        run = ingest_workspace_items(
            db,
            ws,
            chunks,
            source_name=file_name or source_name,
            source_type=source_type,
            layer=normalize_layer(layer),
            memory_type=normalize_memory_type(memory_type),
            actor_user_id=user_id,
            metadata={"split_mode": split_mode, "uploaded_file": file_name},
        )
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="workspace.ingested",
            summary=f"Ingested {run.item_count} item(s) from {run.source_name}",
            metadata={"source_type": run.source_type, "layer": run.layer, "memory_type": run.memory_type},
        )
        db.commit()
        set_flash(request, "success", f"Ingested {run.item_count} item(s) into memory.")
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.post("/app/workspaces/{slug}/invites")
@login_required
async def create_workspace_invite(
    request: Request,
    slug: str,
    email: str = Form(""),
    role: str = Form("member"),
):
    user_id = current_user_id(request)
    email = bounded_text(email, "email", 180)
    role = role if role in {"member", "editor", "admin"} else "member"
    db = SessionLocal()
    try:
        ws, membership = _load_membership_for_user(db, user_id, slug)
        require_workspace_role(membership, {"owner", "admin"})
        invite_token, _prefix, token_hash = mint_prefixed_token("engraminvite")
        invite = WorkspaceInvite(
            workspace_id=ws.id,
            invited_by_user_id=user_id,
            email=email.strip() or None,
            role=role,
            token_hash=token_hash,
            expires_at=utc_now() + timedelta(days=14),
        )
        db.add(invite)
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="workspace.invite.created",
            summary=f"Created a {role} invite",
            metadata={"email": invite.email, "expires_at": invite.expires_at.isoformat()},
        )
        db.commit()
        set_flash(
            request,
            "success",
            f"Invite created. Share {settings.base_url}/app/invites/{invite_token}",
        )
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.post("/app/workspaces/{slug}/keys")
@login_required
async def create_workspace_key(request: Request, slug: str, label: str = Form(...)):
    user_id = current_user_id(request)
    label = bounded_text(label, "label", 80)
    db = SessionLocal()
    try:
        ws, membership = _load_membership_for_user(db, user_id, slug)
        require_workspace_role(membership, {"owner", "admin", "editor"})
        api_token, token_prefix, token_hash = mint_prefixed_token("engram")
        api_key = WorkspaceApiKey(
            workspace_id=ws.id,
            created_by_user_id=user_id,
            label=label,
            token_prefix=token_prefix,
            token_hash=token_hash,
        )
        db.add(api_key)
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="api_key.created",
            summary=f"Created API key {api_key.label}",
            metadata={"label": api_key.label, "token_prefix": token_prefix},
        )
        db.commit()
        set_flash(request, "success", f"API key created. Copy it now: {api_token}")
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.post("/app/workspaces/{slug}/keys/{key_id}/revoke")
@login_required
async def revoke_workspace_key(request: Request, slug: str, key_id: str):
    user_id = current_user_id(request)
    db = SessionLocal()
    try:
        ws, membership = _load_membership_for_user(db, user_id, slug)
        require_workspace_role(membership, {"owner", "admin"})
        api_key = db.execute(
            select(WorkspaceApiKey).where(
                WorkspaceApiKey.id == key_id,
                WorkspaceApiKey.workspace_id == ws.id,
            )
        ).scalar_one_or_none()
        if not api_key:
            raise HTTPException(status_code=404, detail="API key not found")
        api_key.revoked_at = utc_now()
        record_audit_event(
            db,
            workspace_id=ws.id,
            actor_user_id=user_id,
            event_type="api_key.revoked",
            summary=f"Revoked API key {api_key.label}",
            metadata={"label": api_key.label, "token_prefix": api_key.token_prefix},
        )
        db.commit()
        set_flash(request, "success", "API key revoked.")
    finally:
        db.close()
    return RedirectResponse(f"/app/workspaces/{slug}", status_code=302)


@app.get("/app/invites/{token}", response_class=HTMLResponse)
@login_required
async def invite_page(request: Request, token: str):
    user_id = current_user_id(request)
    token_hash = digest_token(token)
    db = SessionLocal()
    try:
        invite = db.execute(
            select(WorkspaceInvite, Workspace, User)
            .join(Workspace, Workspace.id == WorkspaceInvite.workspace_id)
            .join(User, User.id == WorkspaceInvite.invited_by_user_id)
            .where(
                WorkspaceInvite.token_hash == token_hash,
                WorkspaceInvite.revoked_at.is_(None),
            )
        ).first()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        invite_row, workspace, inviter = invite
        if invite_row.expires_at and invite_row.expires_at < utc_now():
            raise HTTPException(status_code=410, detail="Invite expired")
        existing = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user_id,
            )
        ).scalar_one_or_none()
        return render(
            request,
            "invite.html",
            invite=invite_row,
            workspace=workspace,
            inviter=inviter,
            already_member=bool(existing),
        )
    finally:
        db.close()


@app.post("/app/invites/{token}/accept")
@login_required
async def accept_invite(request: Request, token: str):
    user_id = current_user_id(request)
    token_hash = digest_token(token)
    db = SessionLocal()
    try:
        invite = db.execute(
            select(WorkspaceInvite, Workspace)
            .join(Workspace, Workspace.id == WorkspaceInvite.workspace_id)
            .where(
                WorkspaceInvite.token_hash == token_hash,
                WorkspaceInvite.revoked_at.is_(None),
            )
        ).first()
        if not invite:
            raise HTTPException(status_code=404, detail="Invite not found")
        invite_row, workspace = invite
        if invite_row.expires_at and invite_row.expires_at < utc_now():
            raise HTTPException(status_code=410, detail="Invite expired")
        existing = db.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user_id,
            )
        ).scalar_one_or_none()
        if not existing:
            db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user_id, role=invite_row.role))
        invite_row.accepted_at = utc_now()
        record_audit_event(
            db,
            workspace_id=workspace.id,
            actor_user_id=user_id,
            event_type="workspace.invite.accepted",
            summary=f"Accepted invite as {invite_row.role}",
            metadata={"role": invite_row.role},
        )
        db.commit()
        set_flash(request, "success", f"You joined {workspace.name}.")
        return RedirectResponse(f"/app/workspaces/{workspace.slug}", status_code=302)
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/status")
async def api_workspace_status(
    slug: str,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        record_api_event(db, workspace.id, api_key.id, "/status", "GET")
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "stats": workspace_status(workspace.schema_name)})
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/memories/recent")
async def api_workspace_recent(
    slug: str,
    limit: int = 10,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        safe_limit = bounded_int(limit, default=10, minimum=1, maximum=100)
        record_api_event(db, workspace.id, api_key.id, "/memories/recent", "GET", metadata={"limit": safe_limit})
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "memories": workspace_recent_memories(workspace.schema_name, limit=safe_limit)})
    finally:
        db.close()


@app.post("/api/workspaces/{slug}/search")
async def api_workspace_search(
    slug: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    payload = await request.json()
    query = bounded_text(payload.get("query") or "", "query", 500)
    top_k = bounded_int(payload.get("top_k"), default=8, minimum=1, maximum=50)
    if not query:
        raise HTTPException(status_code=400, detail="query is required")
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        record_api_event(db, workspace.id, api_key.id, "/search", "POST", metadata={"top_k": top_k})
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "results": workspace_search(workspace.schema_name, query=query, top_k=top_k)})
    finally:
        db.close()


@app.post("/api/workspaces/{slug}/remember")
async def api_workspace_remember(
    slug: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    payload = await request.json()
    content = bounded_text(payload.get("content") or "", "content", 20_000)
    layer = payload.get("layer") or "episodic"
    memory_type = payload.get("memory_type") or "narrative"
    if not content:
        raise HTTPException(status_code=400, detail="content is required")
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        result = workspace_remember(workspace.schema_name, content=content, layer=layer, memory_type=memory_type)
        record_audit_event(
            db,
            workspace_id=workspace.id,
            actor_user_id=None,
            event_type="memory.remembered.api",
            summary=f"API key {api_key.label} stored a {memory_type} memory",
            metadata={"layer": layer, "memory_type": memory_type, "preview": content[:180]},
        )
        record_api_event(
            db,
            workspace.id,
            api_key.id,
            "/remember",
            "POST",
            metadata={"layer": layer, "memory_type": memory_type},
        )
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "result": result})
    finally:
        db.close()


@app.post("/api/workspaces/{slug}/ingest")
async def api_workspace_ingest(
    slug: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    payload = await request.json()
    source_name = bounded_text(payload.get("source_name") or "api import", "source_name", 180)
    source_type = bounded_text(payload.get("source_type") or "json", "source_type", 80)
    layer = normalize_layer(payload.get("layer"))
    memory_type = normalize_memory_type(payload.get("memory_type"))
    split_mode = payload.get("split_mode") or "auto"
    items = payload.get("items")
    if isinstance(items, list):
        ingest_items = [
            bounded_text(json.dumps(item, ensure_ascii=False) if not isinstance(item, str) else item, "ingest item", 20_000)
            for item in items[:100]
        ]
    else:
        ingest_items = split_ingest_text(bounded_text(str(payload.get("content") or ""), "content", 200_000), mode=split_mode)
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        run = ingest_workspace_items(
            db,
            workspace,
            ingest_items,
            source_name=source_name,
            source_type=source_type,
            layer=layer,
            memory_type=memory_type,
            api_key_id=api_key.id,
            metadata={"split_mode": split_mode},
        )
        record_audit_event(
            db,
            workspace_id=workspace.id,
            actor_user_id=None,
            event_type="workspace.ingested.api",
            summary=f"API key {api_key.label} ingested {run.item_count} item(s)",
            metadata={"source_name": run.source_name, "source_type": run.source_type},
        )
        record_api_event(
            db,
            workspace.id,
            api_key.id,
            "/ingest",
            "POST",
            metadata={"item_count": run.item_count, "source_type": run.source_type},
        )
        db.commit()
        return JSONResponse(
            {
                "workspace": workspace.slug,
                "ingest": {
                    "source_name": run.source_name,
                    "source_type": run.source_type,
                    "item_count": run.item_count,
                    "character_count": run.character_count,
                    "layer": run.layer,
                    "memory_type": run.memory_type,
                },
            }
        )
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/audit")
async def api_workspace_audit(
    slug: str,
    limit: int = 25,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        safe_limit = bounded_int(limit, default=25, minimum=1, maximum=100)
        record_api_event(db, workspace.id, api_key.id, "/audit", "GET", metadata={"limit": safe_limit})
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "events": _workspace_audit_feed(db, workspace.id, limit=safe_limit)})
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/ingest/runs")
async def api_workspace_ingest_runs(
    slug: str,
    limit: int = 25,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        safe_limit = bounded_int(limit, default=25, minimum=1, maximum=100)
        record_api_event(db, workspace.id, api_key.id, "/ingest/runs", "GET", metadata={"limit": safe_limit})
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "runs": _workspace_ingest_runs(db, workspace.id, limit=safe_limit)})
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/export/recent")
async def api_workspace_export_recent(
    slug: str,
    limit: int = 100,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        safe_limit = bounded_int(limit, default=100, minimum=1, maximum=250)
        record_api_event(db, workspace.id, api_key.id, "/export/recent", "GET", metadata={"limit": safe_limit})
        db.commit()
        return JSONResponse(
            {
                "workspace": workspace.slug,
                "exported_at": utc_now().isoformat(),
                "memories": workspace_recent_memories(workspace.schema_name, limit=safe_limit),
            }
        )
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/usage")
async def api_workspace_usage(
    slug: str,
    limit: int = 50,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        safe_limit = bounded_int(limit, default=50, minimum=1, maximum=100)
        record_api_event(db, workspace.id, api_key.id, "/usage", "GET", metadata={"limit": safe_limit})
        db.commit()
        return JSONResponse(
            {
                "workspace": workspace.slug,
                "summary": _workspace_api_usage_summary(db, workspace.id),
                "events": _workspace_api_usage_feed(db, workspace.id, limit=safe_limit),
            }
        )
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/bootstrap")
async def api_workspace_bootstrap(
    slug: str,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        base_headers = {"Authorization": "Bearer <workspace-api-key>"}
        record_api_event(db, workspace.id, api_key.id, "/bootstrap", "GET")
        db.commit()
        return JSONResponse(
            {
                "workspace": workspace.slug,
                "service": {
                    "name": "Memorylayer",
                    "base_url": settings.base_url,
                    "mcp_bridge_url": f"{settings.base_url}/api/workspaces/{workspace.slug}/mcp",
                    "docs_url": f"{settings.base_url}/docs",
                    "connect_url": f"{settings.base_url}/connect",
                    "openapi_url": f"{settings.base_url}/openapi.json",
                },
                "api": {
                    "status_url": workspace_endpoint_map(workspace)["status"],
                    "search_url": workspace_endpoint_map(workspace)["search"],
                    "remember_url": workspace_endpoint_map(workspace)["remember"],
                    "recent_url": workspace_endpoint_map(workspace)["recent"],
                    "audit_url": workspace_endpoint_map(workspace)["audit"],
                    "usage_url": workspace_endpoint_map(workspace)["usage"],
                    "ingest_url": workspace_endpoint_map(workspace)["ingest"],
                    "ingest_runs_url": workspace_endpoint_map(workspace)["ingest_runs"],
                    "recent_export_url": workspace_endpoint_map(workspace)["export_recent"],
                    "connect_config_url": f"{settings.base_url}/api/workspaces/{workspace.slug}/connect",
                    "env_url": f"{settings.base_url}/api/workspaces/{workspace.slug}/env",
                    "headers": base_headers,
                },
                "mcp": {
                    "transport": "http-json",
                    "tools_url": f"{settings.base_url}/api/workspaces/{workspace.slug}/mcp/tools",
                    "tool_names": [tool["name"] for tool in SUPPORTED_TOOLS],
                    "headers": base_headers,
                },
                "skills": [
                    {
                        "name": skill["name"],
                        "title": skill["title"],
                        "download_url": f"{settings.base_url}/api/skills/{skill['name']}",
                        "markdown_url": f"{settings.base_url}/api/skills/{skill['name']}.md",
                    }
                    for skill in starter_skill_list()
                ],
                "api_key": {"label": api_key.label, "prefix": api_key.token_prefix},
            }
        )
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/connect")
async def api_workspace_connect(
    slug: str,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        record_api_event(db, workspace.id, api_key.id, "/connect", "GET")
        db.commit()
        return JSONResponse(workspace_connection_kit(workspace, api_key_label=api_key.label, token_hint=f"{api_key.token_prefix}..."))
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/env")
async def api_workspace_env(
    slug: str,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        record_api_event(db, workspace.id, api_key.id, "/env", "GET")
        db.commit()
        return PlainTextResponse(
            render_workspace_env(workspace, token_hint=f"{api_key.token_prefix}..."),
            media_type="text/plain; charset=utf-8",
        )
    finally:
        db.close()


@app.post("/api/workspaces/{slug}/mcp")
async def api_workspace_mcp(
    slug: str,
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    payload = await request.json()
    tool_name = bounded_text(payload.get("tool") or "", "tool", 80)
    args = payload.get("args") or {}
    if not isinstance(args, dict):
        raise HTTPException(status_code=400, detail="args must be an object")
    if not tool_name:
        raise HTTPException(status_code=400, detail="tool is required")

    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        try:
            result = workspace_tool_call(workspace.schema_name, tool_name, args)
        except ValueError as exc:
            record_api_event(
                db,
                workspace.id,
                api_key.id,
                "/mcp",
                "POST",
                status_code=400,
                metadata={"tool": tool_name, "error": str(exc)},
            )
            db.commit()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        record_audit_event(
            db,
            workspace_id=workspace.id,
            actor_user_id=None,
            event_type="mcp.tool.called",
            summary=f"API key {api_key.label} called {tool_name}",
            metadata={"tool": tool_name},
        )
        record_api_event(db, workspace.id, api_key.id, "/mcp", "POST", metadata={"tool": tool_name})
        db.commit()
        return JSONResponse({"workspace": workspace.slug, "tool": tool_name, "result": result})
    finally:
        db.close()


@app.get("/api/workspaces/{slug}/mcp/tools")
async def api_workspace_mcp_tools(
    slug: str,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    db = SessionLocal()
    try:
        workspace, api_key = require_api_workspace(db, slug, authorization, x_api_key)
        record_api_event(db, workspace.id, api_key.id, "/mcp/tools", "GET")
        db.commit()
        return JSONResponse(
            {
                "workspace": workspace.slug,
                "transport": "http-json",
                "call_url": f"{settings.base_url}/api/workspaces/{workspace.slug}/mcp",
                "tools": SUPPORTED_TOOLS,
            }
        )
    finally:
        db.close()


@app.get("/api/skills")
async def api_skills_index():
    return JSONResponse({"skills": starter_skill_list()})


@app.get("/api/skills/{skill_name}.md")
async def api_skill_markdown(skill_name: str):
    body = render_skill_markdown(skill_name)
    if body is None:
        raise HTTPException(status_code=404, detail="Skill not found")
    return PlainTextResponse(body, media_type="text/markdown; charset=utf-8")


@app.get("/api/skills/{skill_name}")
async def api_skill_download(skill_name: str):
    skill = STARTER_SKILLS.get(skill_name)
    if not skill:
        raise HTTPException(status_code=404, detail="Skill not found")
    return JSONResponse(skill)
