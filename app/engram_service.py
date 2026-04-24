from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from engram.config import Config
from engram.mcp_server import MCPServer

from app.config import settings
from app.db import engine


TOOL_METHODS = {
    "status": "_status",
    "health": "_health",
    "memory_map": "_memory_map",
    "quality_metrics": "_quality_metrics",
    "count_by": "_count_by",
    "access_patterns": "_access_patterns",
    "reranker_status": "_reranker_status",
    "recall": "_recall",
    "recall_context": "_recall_context",
    "recall_hints": "_recall_hints",
    "recall_recent": "_recall_recent",
    "recall_entity": "_recall_entity",
    "recall_by_type": "_recall_by_type",
    "recall_layer": "_recall_layer",
    "recall_timeline": "_recall_timeline",
    "recall_related": "_recall_related",
    "recall_explain": "_recall_explain",
    "search_entities": "_search_entities",
    "entity_graph": "_entity_graph",
    "entity_timeline": "_entity_timeline",
    "backlinks": "_backlinks",
    "find_similar": "_find_similar",
    "layers": "_layers",
    "get_skills": "_get_skills",
    "remember": "_remember",
    "remember_decision": "_remember_decision",
    "remember_error": "_remember_error",
    "remember_interaction": "_remember_interaction",
    "remember_negative": "_remember_negative",
    "remember_project": "_remember_project",
    "diary_read": "_diary_read",
    "diary_write": "_diary_write",
    "session_checkpoint": "_session_checkpoint",
    "session_handoff": "_session_handoff",
    "resume_context": "_resume_context",
    "focus_brief": "_focus_brief",
    "hotspots": "_hotspots",
    "compare_queries": "_compare_queries",
    "export": "_export",
    "compress": "_compress",
    "annotate": "_annotate",
    "edit_memory": "_edit_memory",
    "invalidate": "_invalidate",
    "update_status": "_update_status",
    "status_history": "_status_history",
    "tag": "_tag",
    "pin": "_pin",
    "forget": "_forget",
    "promote": "_promote",
    "demote": "_demote",
    "unpin": "_unpin",
    "link_memories": "_link_memories",
    "update_entity": "_update_entity",
    "merge_entities": "_merge_entities",
    "batch_tag": "_batch_tag",
    "dedup": "_dedup",
    "detect_communities": "_detect_communities",
    "consolidate": "_consolidate",
    "extract_patterns": "_extract_patterns",
    "session_summary": "_session_summary",
}

MAX_WORKSPACE_RUNTIMES = 16
RUNTIME_IDLE_TTL_SECONDS = 60 * 30


@dataclass
class WorkspaceRuntime:
    schema_name: str
    config: Config
    server: MCPServer
    lock: threading.RLock
    last_used_at: float

    @property
    def store(self):
        return self.server.store

    def close(self) -> None:
        self.server.store.close()


_runtime_cache: OrderedDict[str, WorkspaceRuntime] = OrderedDict()
_runtime_cache_lock = threading.RLock()


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
    return f"{base}{sep}options={quote(f'-c search_path={schema_name}', safe='')}"


def workspace_config(schema_name: str) -> Config:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_dir: Path = settings.data_dir / schema_name
    db_dir.mkdir(parents=True, exist_ok=True)
    cfg = Config.load()
    cfg.storage_backend = "postgres"
    cfg.postgres_dsn = workspace_engram_dsn(schema_name)
    cfg.db_path = db_dir / "memory.db"
    return cfg


def _close_runtime(runtime: WorkspaceRuntime) -> None:
    try:
        with runtime.lock:
            runtime.close()
    except Exception:
        pass


def _prune_runtime_cache(now: float) -> None:
    expired = [
        schema_name
        for schema_name, runtime in _runtime_cache.items()
        if now - runtime.last_used_at > RUNTIME_IDLE_TTL_SECONDS
    ]
    for schema_name in expired:
        _close_runtime(_runtime_cache.pop(schema_name))

    while len(_runtime_cache) > MAX_WORKSPACE_RUNTIMES:
        _schema_name, runtime = _runtime_cache.popitem(last=False)
        _close_runtime(runtime)


def workspace_runtime(schema_name: str) -> WorkspaceRuntime:
    ensure_workspace_schema(schema_name)
    now = time.monotonic()
    with _runtime_cache_lock:
        runtime = _runtime_cache.get(schema_name)
        if runtime:
            runtime.last_used_at = now
            _runtime_cache.move_to_end(schema_name)
            return runtime

        cfg = workspace_config(schema_name)
        server = MCPServer(cfg)
        runtime = WorkspaceRuntime(
            schema_name=schema_name,
            config=cfg,
            server=server,
            lock=threading.RLock(),
            last_used_at=now,
        )
        _runtime_cache[schema_name] = runtime
        _prune_runtime_cache(now)
        return runtime


def close_workspace_runtimes() -> None:
    with _runtime_cache_lock:
        while _runtime_cache:
            _schema_name, runtime = _runtime_cache.popitem(last=False)
            _close_runtime(runtime)


def workspace_runtime_stats() -> dict:
    now = time.monotonic()
    with _runtime_cache_lock:
        return {
            "cached_workspaces": len(_runtime_cache),
            "max_cached_workspaces": MAX_WORKSPACE_RUNTIMES,
            "idle_ttl_seconds": RUNTIME_IDLE_TTL_SECONDS,
            "schemas": [
                {
                    "schema": runtime.schema_name,
                    "idle_seconds": round(now - runtime.last_used_at, 3),
                }
                for runtime in _runtime_cache.values()
            ],
        }


def init_workspace_store(schema_name: str) -> None:
    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        runtime.store.init_db()


def workspace_status(schema_name: str) -> dict:
    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        return runtime.store.get_stats()


def workspace_search(schema_name: str, query: str, top_k: int = 8) -> list[dict]:
    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        return runtime.server._recall({"query": query, "top_k": top_k, "mode": "full_context"})


def workspace_remember(schema_name: str, content: str, layer: str = "episodic", memory_type: str = "narrative") -> dict:
    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        return runtime.server._remember({
            "content": content,
            "layer": layer,
            "memory_type": memory_type,
            "source_type": "remember:human",
        })


def workspace_recent_memories(schema_name: str, limit: int = 10) -> list[dict]:
    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        return [
            {
                "id": m.id,
                "content": m.content,
                "layer": m.layer,
                "importance": m.importance,
                "created_at": m.created_at,
            }
            for m in runtime.store.get_recent_memories(limit=limit)
        ]


def workspace_tool_call(schema_name: str, tool_name: str, args: dict | None = None):
    method_name = TOOL_METHODS.get(tool_name)
    if not method_name:
        raise ValueError(f"Unsupported tool: {tool_name}")

    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        method = getattr(runtime.server, method_name)
        return method(args or {})
