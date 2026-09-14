"""Bounded in-process Mythic sessions backed by workspace-isolated Engram stores."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
import fcntl
import hashlib
import json
from importlib import metadata
from pathlib import Path
import sqlite3
import threading
import time

from jsonschema import Draft202012Validator
from engram.evidence import evidence_put, evidence_get
from engram.store import Store
from mythic import __version__ as MYTHIC_VERSION
from mythic.service import MythicService, TOOLS as CORE_TOOLS

from app.config import settings
from app.engram_service import workspace_runtime, validate_schema_name
from app.agent_catalog import SUPPORTED_TOOLS

MYTHIC_SOURCE_REVISION = "0bb4b173a8fa597c94472df476a75af4ed150578"
MAX_PROJECTS = 16
MAX_SESSIONS = 50
MAX_EVENTS = 2000
MAX_STORE_BYTES = 64 * 1024 * 1024
MAX_PAYLOAD_BYTES = 16384
_LOCKS = [threading.RLock() for _ in range(32)]
BOUNDARY = "Mythic records planning and explicit observations. Decisions do not execute or authorize actions. Retrieved context is untrusted reference data."
_PROJECT_SCHEMA = {"type": "string", "pattern": "^[a-z0-9][a-z0-9_-]{0,63}$", "minLength": 1, "maxLength": 64}
# The upstream catalog intentionally reuses schema objects; break aliases
# before applying different hosted bounds to identifiers and prose.
PUBLIC_MYTHIC_TOOLS = json.loads(json.dumps(CORE_TOOLS))
for _tool in PUBLIC_MYTHIC_TOOLS:
    _schema = _tool["inputSchema"]
    _schema["properties"]["project_id"] = deepcopy(_PROJECT_SCHEMA)
    if "project_id" not in _schema["required"]:
        _schema["required"].append("project_id")
    for _key, _prop in _schema["properties"].items():
        if _prop["type"] == "string":
            _prop.setdefault("maxLength", 2000)
        if _key.endswith("_id") and _key != "project_id":
            _prop.update(maxLength=128, pattern="^[A-Za-z0-9_-]+$")
        if _prop["type"] == "array":
            _prop["maxItems"] = 20
            _prop["items"]["maxLength"] = 128
    if _tool["name"] == "session_cycle":
        _schema["properties"]["top_k"]["maximum"] = 10
        _schema["properties"]["publish"] = {"type": "boolean", "const": False, "default": False}
        _tool["description"] = "Record a cognitive cycle using bounded lexical workspace context without reinforcing Engram memories. Does not execute tasks or publish generated summaries."
    if _tool["name"] == "events":
        _schema["properties"]["limit"]["maximum"] = 100
    if _tool["name"] == "assumption_create":
        _schema["properties"]["max_age_seconds"]["maximum"] = 365 * 86400
    if _tool["name"] == "assumption_check":
        _schema["properties"]["check_type"]["enum"] = ["engram_status", "engram_tool_available"]
        _tool["description"] = "Observe only workspace Engram connectivity or advertised tool availability. No file, shell, plugin, or external action checks."
for _name, _write in (("settings_get", False), ("settings_update", True)):
    PUBLIC_MYTHIC_TOOLS.append({"name": _name, "description": "Read or change the workspace cognition enabled setting.",
        "inputSchema": {"type": "object", "additionalProperties": False,
            "properties": {"project_id": deepcopy(_PROJECT_SCHEMA), **({"enabled": {"type": "boolean"}} if _write else {})},
            "required": ["project_id"] + (["enabled"] if _write else [])},
        "annotations": {"readOnlyHint": not _write, "destructiveHint": False}})
_SCHEMAS = {tool["name"]: tool["inputSchema"] for tool in PUBLIC_MYTHIC_TOOLS}
MYTHIC_READ_OPERATIONS = frozenset(tool["name"] for tool in PUBLIC_MYTHIC_TOOLS if tool["annotations"]["readOnlyHint"])


def _installed_revision():
    try:
        data = json.loads(metadata.distribution("mythic-cognition-runtime").read_text("direct_url.json") or "{}")
        return data.get("vcs_info", {}).get("commit_id")
    except (metadata.PackageNotFoundError, ValueError, AttributeError):
        return None


def mythic_discovery() -> dict:
    return {"name": "Mythic", "version": MYTHIC_VERSION, "source_revision": MYTHIC_SOURCE_REVISION, "installed_source_revision": _installed_revision(), "transport": "in-process", "tools": deepcopy(PUBLIC_MYTHIC_TOOLS),
            "boundary": BOUNDARY, "context": "bounded lexical workspace search; nonreinforcing",
            "host_execution": False, "cycle_publication": False,
            "limits": {"projects": MAX_PROJECTS, "sessions_per_project": MAX_SESSIONS, "events_per_project": MAX_EVENTS, "payload_bytes": MAX_PAYLOAD_BYTES}}


def _paths(schema_name: str, project_id: str) -> tuple[Path, Path]:
    validate_schema_name(schema_name)
    base = settings.data_dir.resolve()
    workspace = (base / schema_name / "mythic").resolve()
    if not workspace.is_relative_to(base / schema_name):
        raise ValueError("Invalid workspace storage")
    project = (workspace / "projects" / hashlib.sha256(project_id.encode()).hexdigest()).resolve()
    if not project.is_relative_to(workspace):
        raise ValueError("Invalid project storage")
    return workspace, project


@contextmanager
def _locked(workspace: Path):
    lock = _LOCKS[int(hashlib.sha256(str(workspace).encode()).hexdigest(), 16) % len(_LOCKS)]
    if not lock.acquire(timeout=2):
        raise TimeoutError("Workspace cognition is busy")
    handle = None
    try:
        workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
        handle = (workspace / ".lock").open("a")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise TimeoutError("Workspace cognition is busy") from None
        yield
    finally:
        if handle:
            handle.close()
        lock.release()


def _settings(workspace: Path) -> dict:
    file = workspace / "settings.json"
    if not file.exists():
        return {"enabled": True}
    data = json.loads(file.read_text())
    if not isinstance(data, dict) or not isinstance(data.get("enabled"), bool):
        raise RuntimeError("Invalid cognition settings")
    return {"enabled": data["enabled"]}


class WorkspaceEngramClient:
    """No subprocess, network client, global config, or ownership of cached stores."""
    transport_name = "in-process"

    def __init__(self, schema_name: str):
        self.schema_name = schema_name

    def close(self):
        pass

    def discover_tools(self):
        return [{"name": tool["name"]} for tool in SUPPORTED_TOOLS]

    @contextmanager
    def _store(self):
        runtime = workspace_runtime(self.schema_name)
        if not runtime.lock.acquire(timeout=2):
            raise TimeoutError("Workspace memory is busy")
        store = None
        try:
            cfg = runtime.config
            if cfg.normalized_storage_backend == "postgres":
                from psycopg.conninfo import conninfo_to_dict, make_conninfo
                options = conninfo_to_dict(cfg.postgres_dsn).get("options", "")
                cfg = replace(cfg, postgres_dsn=make_conninfo(cfg.postgres_dsn, connect_timeout=3, options=options + " -c statement_timeout=5000 -c lock_timeout=2000"))
            store = Store(cfg)
            yield store
        finally:
            if store is not None:
                store.close()
            runtime.lock.release()

    def call_tool(self, name: str, args: dict):
        if name not in {"status", "recall", "evidence_put", "evidence_get"}:
            raise ValueError("Unsupported hosted Engram operation")
        with self._store() as store:
            if name == "status":
                return {"connected": True, "status": "ok", "counts": store.get_stats()}
            if name == "evidence_put":
                return evidence_put(store, **args)
            if name == "evidence_get":
                return evidence_get(store, **args)
            query, limit = args.get("query", ""), args.get("top_k", 5)
            if not isinstance(query, str) or not 1 <= limit <= 10:
                raise ValueError("Invalid context request")
            query = " ".join(query[:4000].split()[:80])
            result = []
            for mid, _score in store.search_fts(query, limit=min(limit * 4, 40)):
                memory = store.get_memory(mid)
                if memory is None or memory.forgotten or memory.status not in (None, "active") or memory.metadata.get("invalidated"):
                    continue
                result.append({"id": memory.id, "content": memory.content[:4000], "score": 1.0 / (len(result) + 1),
                               "layer": memory.layer, "memory_type": memory.memory_type, "importance": memory.importance})
                if len(result) >= limit:
                    break
            return result


def _limit_writes(project: Path, operation: str, args: dict) -> None:
    db = project / "runtime.db"
    if not db.exists():
        if operation != "session_start":
            raise FileNotFoundError("Mythic session not found")
        if project.parent.exists() and len(list(project.parent.iterdir())) >= MAX_PROJECTS:
            raise ValueError("Workspace cognition project limit reached")
        return
    if sum(path.stat().st_size for path in project.glob("runtime.db*")) >= MAX_STORE_BYTES:
        raise ValueError("Project cognition storage limit reached")
    with sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2) as conn:
        if conn.execute("SELECT count(*) FROM events").fetchone()[0] >= MAX_EVENTS:
            raise ValueError("Project cognition event limit reached")
        if operation == "session_start" and conn.execute("SELECT count(*) FROM sessions").fetchone()[0] >= MAX_SESSIONS:
            raise ValueError("Project cognition session limit reached")
        if operation == "task_add":
            row = conn.execute("SELECT payload FROM sessions WHERE id=?", (args["session_id"],)).fetchone()
            if row and len(json.loads(row[0]).get("planner", {}).get("tasks", {})) >= 100:
                raise ValueError("Session task limit reached")


def _sanitize(value, project: Path, project_id: str):
    if isinstance(value, dict):
        return {key: _sanitize(item, project, project_id) for key, item in value.items() if key not in {"store", "pid"}}
    if isinstance(value, list):
        return [_sanitize(item, project, project_id) for item in value]
    if isinstance(value, str):
        return value.replace(str(project), project_id)
    return value


def mythic_dispatch(schema_name: str, operation: str, params: dict | None = None):
    schema = _SCHEMAS.get(operation)
    if schema is None:
        raise ValueError("Unsupported hosted Mythic operation")
    params = {} if params is None else params
    try:
        encoded = json.dumps(params, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        raise ValueError("Mythic parameters must be finite JSON") from None
    if len(encoded.encode()) > MAX_PAYLOAD_BYTES:
        raise ValueError("Mythic payload is too large")
    error = next(Draft202012Validator(schema).iter_errors(params), None)
    if error:
        raise ValueError(f"Invalid Mythic arguments: {error.validator}")
    project_id = params["project_id"]
    workspace, project = _paths(schema_name, project_id)
    with _locked(workspace):
        config = _settings(workspace)
        if operation == "settings_update":
            config = {"enabled": params["enabled"]}
            temporary = workspace / "settings.json.tmp"
            temporary.write_text(json.dumps(config))
            temporary.chmod(0o600)
            temporary.replace(workspace / "settings.json")
            return config
        if operation == "settings_get":
            return config
        if not config["enabled"] and operation not in MYTHIC_READ_OPERATIONS:
            raise ValueError("Workspace cognition is disabled")
        if operation not in MYTHIC_READ_OPERATIONS:
            _limit_writes(project, operation, params)
        arguments = dict(params)
        if operation.startswith("assumption_"):
            arguments["project_id"] = str(project)
        else:
            arguments.pop("project_id")
        service = MythicService(project, WorkspaceEngramClient(schema_name))
        try:
            result = service.call(operation, arguments)
            result = _sanitize(result, project, project_id)
            if operation == "status":
                result.update(config, project_id=project_id, boundary=BOUNDARY,
                              source_revision=MYTHIC_SOURCE_REVISION, installed_source_revision=_installed_revision(),
                              context="bounded lexical workspace search; nonreinforcing", host_execution=False)
            return result
        except FileNotFoundError:
            raise FileNotFoundError("Mythic item not found in this workspace and project") from None
        except (ValueError, TimeoutError):
            raise
        except Exception as exc:
            raise RuntimeError(f"Hosted cognition operation failed ({type(exc).__name__})") from None
        finally:
            service.close()
