from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, replace
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import text

from engram.config import Config
from engram.mcp_server import MCPServer
from engram.evidence import evidence_put, evidence_get, evidence_list
from jsonschema import Draft202012Validator

from app.agent_catalog import EXTENDED_TOOL_SCHEMAS

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

ENGRAM_SOURCE_REVISION = "bec09d48858fcac554648410285e793131f2c915"
EVIDENCE_HANDLERS = {"evidence_put": evidence_put, "evidence_get": evidence_get, "evidence_list": evidence_list}
TOOL_METHODS.update({name: "_" + name for name in ("dormant_review", "dormant_inspect", "dormant_feedback")})


class WorkspaceServer(MCPServer):
    """Keep the core adapter's legacy process-global diary out of tenant calls."""

    def __init__(self, config: Config):
        # Own index initialization inside the runtime lifetime. The core's
        # daemon rebuild can race a closed connection or process shutdown.
        startup = replace(config, ann=replace(config.ann, enabled=False))
        super().__init__(startup)
        self.config = config
        self.store.config = config
        self.store.init_ann_index(background=False)
        self._workspace_diary: list[str] = []

    # The pinned core uses literal percent signs in these bound queries.
    # Parameterize patterns for psycopg and constrain both read types to one hour.
    def _memory_map(self, args: dict):
        stats = self.store.get_stats()

        # top entities per layer
        layers_detail = {}
        for layer in ["working", "episodic", "semantic", "procedural", "codebase"]:
            top = self.store.conn.execute(
                """SELECT e.canonical_name, COUNT(em.memory_id) as cnt
                   FROM entity_mentions em
                   JOIN memories m ON m.id = em.memory_id
                   JOIN entities e ON e.id = em.entity_id
                   WHERE m.layer = ? AND m.forgotten = 0
                   GROUP BY e.id ORDER BY cnt DESC LIMIT 5""",
                (layer,),
            ).fetchall()
            layers_detail[layer] = {
                "count": stats["memories"].get(layer, 0),
                "top_entities": [{"name": r["canonical_name"], "count": r["cnt"]} for r in top],
            }

        # oldest and newest
        oldest = self.store.conn.execute(
            "SELECT fact_date, content FROM memories WHERE forgotten=0 AND fact_date IS NOT NULL ORDER BY fact_date ASC LIMIT 1"
        ).fetchone()
        newest = self.store.conn.execute(
            "SELECT fact_date, content FROM memories WHERE forgotten=0 AND fact_date IS NOT NULL ORDER BY fact_date DESC LIMIT 1"
        ).fetchone()

        # recent activity
        recent_writes = self.store.conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE event_type LIKE ? AND created_at > ?",
            ("%write%", time.time() - 3600),
        ).fetchone()["cnt"]
        recent_reads = self.store.conn.execute(
            "SELECT COUNT(*) as cnt FROM events WHERE (event_type LIKE ? OR event_type = 'recall') AND created_at > ?",
            ("%read%", time.time() - 3600),
        ).fetchone()["cnt"]

        return {
            **stats,
            "layers": layers_detail,
            "date_range": {
                "oldest": dict(oldest) if oldest else None,
                "newest": dict(newest) if newest else None,
            },
            "last_hour": {"writes": recent_writes, "reads": recent_reads},
        }

    # PostgreSQL stores aliases as JSONB; LOWER requires an explicit text cast.
    def _search_entities(self, args: dict):
        query = args["query"].lower()
        rows = self.store.conn.execute(
            """SELECT e.id, e.canonical_name, e.entity_type, e.aliases,
                      COUNT(em.memory_id) as mem_count
               FROM entities e
               LEFT JOIN entity_mentions em ON em.entity_id = e.id
               WHERE LOWER(e.canonical_name) LIKE ?
                  OR LOWER(CAST(e.aliases AS TEXT)) LIKE ?
               GROUP BY e.id
               ORDER BY mem_count DESC
               LIMIT ?""",
            (f"%{query}%", f"%{query}%", args.get("limit", 20)),
        ).fetchall()
        return {"entities": [dict(r) for r in rows]}

    def _diary_write(self, args: dict):
        entry = f"[{time.strftime('%H:%M:%S')}] {args['entry']}"
        self.store.write_diary(entry, session_id=self._session_id)
        self._workspace_diary.append(entry)
        self._refresh_session_handoff()
        return {"status": "written", "entries": len(self._workspace_diary)}

    def _diary_read(self, args: dict):
        entries = self.store.get_diary(limit=50)
        return {"diary": [entry["text"] for entry in entries] or list(self._workspace_diary)}

    def _session_checkpoint(self, args: dict):
        note = (args.get("note") or "").strip()
        if note:
            entry = f"[checkpoint] {note}"
            self.store.write_diary(entry, session_id=self._session_id)
            self._workspace_diary.append(entry)
        handoff = self._build_session_handoff(self._session_id, limit=args.get("limit", 8))
        handoff["checkpoint_note"] = note or None
        self.store.save_session_handoff(self._session_id, handoff["summary"], handoff)
        return handoff


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


def validate_schema_name(schema_name: str) -> None:
    if not re.fullmatch(r"ws_[a-z0-9_]{1,48}", schema_name):
        raise ValueError("Invalid workspace schema")


def ensure_workspace_schema(schema_name: str) -> None:
    validate_schema_name(schema_name)
    with engine.begin() as conn:
        conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"'))


def workspace_engram_dsn(schema_name: str) -> str:
    base = settings.engram_postgres_dsn
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}options={quote(f'-c search_path={schema_name}', safe='')}"


def workspace_config(schema_name: str) -> Config:
    validate_schema_name(schema_name)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db_dir: Path = settings.data_dir / schema_name
    db_dir.mkdir(parents=True, exist_ok=True)
    cfg = Config.load()
    cfg.storage_backend = "postgres"
    cfg.postgres_dsn = workspace_engram_dsn(schema_name)
    cfg.db_path = str((db_dir / "memory.db").resolve())
    cfg.ann.index_path = str((db_dir / "hnsw.index").resolve())
    # Enabling collection requires a separate per-workspace rollout. Review of
    # existing telemetry remains available without enabling shadow collection.
    cfg.dormant_recall.mode = "off"
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
        server = WorkspaceServer(cfg)
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
    if not method_name and tool_name not in EVIDENCE_HANDLERS:
        raise ValueError(f"Unsupported tool: {tool_name}")
    args = {} if args is None else args
    if not isinstance(args, dict):
        raise ValueError("args must be an object")
    if tool_name in EXTENDED_TOOL_SCHEMAS:
        errors = sorted(Draft202012Validator(EXTENDED_TOOL_SCHEMAS[tool_name]).iter_errors(args), key=lambda error: str(error.path))
        if errors:
            # Do not echo rejected values (which may contain observations or secrets).
            field = str(next(iter(errors[0].path), "args"))
            raise ValueError(f"Invalid {tool_name} arguments at {field}: {errors[0].validator}")

    runtime = workspace_runtime(schema_name)
    with runtime.lock:
        if tool_name in EVIDENCE_HANDLERS:
            return EVIDENCE_HANDLERS[tool_name](runtime.store, **args)
        method = getattr(runtime.server, method_name)
        return method(args)
