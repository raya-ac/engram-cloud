from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote_plus

from sqlalchemy import text

from engram.config import Config
from engram.mcp_server import MCPServer
from engram.store import Store

from app.config import settings
from app.db import engine


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-")[:48] or "workspace"


def schema_name_for_slug(slug: str) -> str:
    return "ws_" + slug.replace("-", "_")


def ensure_workspace_schema(schema_name: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))


def workspace_engram_dsn(schema_name: str) -> str:
    base = settings.engram_postgres_dsn
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}options={quote_plus(f'-c search_path={schema_name}')}"


def workspace_config(schema_name: str) -> Config:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_dir: Path = settings.data_dir / schema_name
    db_dir.mkdir(parents=True, exist_ok=True)
    cfg = Config.load()
    cfg.storage_backend = "postgres"
    cfg.postgres_dsn = workspace_engram_dsn(schema_name)
    cfg.db_path = db_dir / "memory.db"
    return cfg


def init_workspace_store(schema_name: str) -> None:
    ensure_workspace_schema(schema_name)
    store = Store(workspace_config(schema_name))
    store.init_db()
    store.close()


def workspace_status(schema_name: str) -> dict:
    store = Store(workspace_config(schema_name))
    try:
        return store.get_stats()
    finally:
        store.close()


def workspace_search(schema_name: str, query: str, top_k: int = 8) -> list[dict]:
    server = MCPServer(workspace_config(schema_name))
    try:
        return server._recall({"query": query, "top_k": top_k, "mode": "full_context"})
    finally:
        server.store.close()


def workspace_remember(schema_name: str, content: str, layer: str = "episodic", memory_type: str = "narrative") -> dict:
    server = MCPServer(workspace_config(schema_name))
    try:
        return server._remember({
            "content": content,
            "layer": layer,
            "memory_type": memory_type,
            "source_type": "remember:human",
        })
    finally:
        server.store.close()


def workspace_recent_memories(schema_name: str, limit: int = 10) -> list[dict]:
    store = Store(workspace_config(schema_name))
    try:
        return [
            {
                "id": m.id,
                "content": m.content,
                "layer": m.layer,
                "importance": m.importance,
                "created_at": m.created_at,
            }
            for m in store.get_recent_memories(limit=limit)
        ]
    finally:
        store.close()
