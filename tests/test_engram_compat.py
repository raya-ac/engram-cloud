"""Pinned Engram compatibility using isolated stores; no live data or model calls."""
import os
import threading
import time
import uuid
from pathlib import Path

import pytest
import numpy as np
from engram.config import Config
from engram.store import Memory
from engram import dormant, mcp_server

from app import engram_service as service
from app.agent_catalog import SUPPORTED_TOOLS, EXTENDED_TOOL_SCHEMAS


@pytest.fixture(params=["sqlite", "postgres"])
def runtimes(request, tmp_path, monkeypatch):
    dsn = os.environ.get("ENGRAM_TEST_POSTGRES_DSN")
    if request.param == "postgres" and not dsn:
        pytest.skip("Set ENGRAM_TEST_POSTGRES_DSN to an isolated disposable cluster")
    instances = {}
    for name in ("alpha", "beta"):
        cfg = Config(db_path=str(tmp_path / name / "memory.db"))
        cfg.ann.enabled = False
        schema = "ws_test_" + uuid.uuid4().hex
        if request.param == "postgres":
            import psycopg
            from psycopg.conninfo import make_conninfo
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'CREATE SCHEMA "{schema}"')
            cfg.storage_backend = "postgres"
            cfg.postgres_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
        server = service.WorkspaceServer(cfg)
        instances[name] = service.WorkspaceRuntime(schema, cfg, server, threading.RLock(), time.monotonic())
    monkeypatch.setattr(service, "workspace_runtime", instances.__getitem__)
    yield instances
    for runtime in instances.values():
        runtime.close()
        if request.param == "postgres":
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'DROP SCHEMA "{runtime.schema_name}" CASCADE')


def test_all_advertised_tools_have_pinned_handlers():
    names = {tool["name"] for tool in SUPPORTED_TOOLS}
    assert names == set(service.TOOL_METHODS) | set(service.EVIDENCE_HANDLERS)
    for method in service.TOOL_METHODS.values():
        assert callable(getattr(service.WorkspaceServer, method, None)), method
    assert len(EXTENDED_TOOL_SCHEMAS) == 6


def test_workspace_config_keeps_indexes_and_shadow_scoped(tmp_path, monkeypatch):
    monkeypatch.setattr(service.settings, "data_dir", tmp_path)
    def inherited_config():
        cfg = Config()
        cfg.dormant_recall.mode = "shadow"
        cfg.ann.index_path = "/unrelated/index"
        return cfg
    monkeypatch.setattr(service.Config, "load", inherited_config)
    a, b = service.workspace_config("ws_alpha"), service.workspace_config("ws_beta")
    assert a.postgres_dsn != b.postgres_dsn
    assert a.resolved_db_path != b.resolved_db_path
    assert a.ann.resolved_index_path != b.ann.resolved_index_path
    assert a.ann.resolved_index_path.is_relative_to(tmp_path / "ws_alpha")
    assert a.dormant_recall.mode == b.dormant_recall.mode == "off"
    for bad in ("../outside", 'ws_a";drop', "public", "ws_" + "x" * 49):
        with pytest.raises(ValueError, match="schema"):
            service.workspace_config(bad)


@pytest.mark.parametrize("tool,args", [
    ("evidence_put", {}),
    ("evidence_get", {"project_id": "/project", "id": "a", "extra": True}),
    ("evidence_list", {"project_id": "/project", "limit": True}),
    ("dormant_review", {"limit": 101}),
    ("dormant_review", {"limit": "secret-value"}),
    ("dormant_inspect", {"event_id": {"secret-value": True}}),
    ("dormant_feedback", {"event_id": "x", "category": "secret-value"}),
])
def test_invalid_new_arguments_rejected_before_runtime(tool, args, monkeypatch):
    monkeypatch.setattr(service, "workspace_runtime", lambda _: pytest.fail("invalid input touched runtime"))
    with pytest.raises(ValueError) as caught:
        service.workspace_tool_call("alpha", tool, args)
    assert "secret-value" not in str(caught.value)


def test_evidence_isolation_persistence_and_no_reinforcement(runtimes, tmp_path):
    now = time.time()
    payload = {"project_id": str(tmp_path / "project"), "session_id": "test-session",
               "assumption_id": "readiness", "evidence_id": "observation-1",
               "outcome": "supported", "observed_at": now, "expires_at": now + 3600,
               "observation": {"fixture": True},
               "provenance": {"producer": "test", "check_type": "fixture"}}
    stored = service.workspace_tool_call("alpha", "evidence_put", payload)
    before = dict(runtimes["alpha"].store.conn.execute("SELECT * FROM memories WHERE id=?", (stored["id"],)).fetchone())
    args = {"project_id": payload["project_id"], "id": stored["id"]}
    read = service.workspace_tool_call("alpha", "evidence_get", args)
    assert read["observation"] == {"fixture": True}
    assert read["verified_by_engram"] is False
    assert service.workspace_tool_call("beta", "evidence_get", args)["state"] == "unknown"
    assert service.workspace_tool_call("beta", "evidence_list", {"project_id": payload["project_id"]}) == []
    assert service.workspace_tool_call("alpha", "evidence_list", {"project_id": payload["project_id"]})[0]["id"] == stored["id"]
    assert dict(runtimes["alpha"].store.conn.execute("SELECT * FROM memories WHERE id=?", (stored["id"],)).fetchone()) == before
    with pytest.raises(ValueError, match="immutable"):
        service.workspace_tool_call("alpha", "evidence_put", {**payload, "outcome": "contradicted"})
    runtimes["alpha"].store.forget_memory(stored["id"])
    assert service.workspace_tool_call("alpha", "evidence_get", args)["reason"] == "forgotten"


def test_dormant_review_inspect_feedback_stay_in_workspace(runtimes):
    runtime = runtimes["alpha"]
    now = time.time()
    memory = Memory(id="fixture-memory", content="isolated fixture", created_at=now - 86400 * 90, last_accessed=now - 86400 * 90)
    runtime.store.save_memory(memory)
    before = dict(runtime.store.conn.execute("SELECT * FROM memories WHERE id=?", (memory.id,)).fetchone())
    assert service.workspace_tool_call("alpha", "dormant_review", {}) == []
    # Seed isolated historical telemetry, without enabling shadow collection.
    with dormant._transaction(runtime.config) as db:
        db.conn.execute("INSERT INTO dormant_recall_events (id,sequence,created_at,memory_id,outcome,candidate_count,relevance,query_term_count) VALUES ('fixture-event',1,?,?,'candidate',1,0.9,1)", (now, memory.id))
    assert service.workspace_tool_call("alpha", "dormant_review", {})[0]["id"] == "fixture-event"
    assert service.workspace_tool_call("beta", "dormant_review", {}) == []
    with pytest.raises(ValueError, match="retained"):
        service.workspace_tool_call("beta", "dormant_inspect", {"event_id": "fixture-event"})
    with pytest.raises(ValueError, match="Inspect"):
        service.workspace_tool_call("alpha", "dormant_feedback", {"event_id": "fixture-event", "category": "useful"})
    assert service.workspace_tool_call("alpha", "dormant_inspect", {"event_id": "fixture-event"})["content"] == memory.content
    assert service.workspace_tool_call("alpha", "dormant_feedback", {"event_id": "fixture-event", "category": "dismissed"})["feedback"] == "dismissed"
    assert dict(runtime.store.conn.execute("SELECT * FROM memories WHERE id=?", (memory.id,)).fetchone()) == before
    runtime.store.forget_memory(memory.id)
    with pytest.raises(ValueError, match="eligible|retained"):
        service.workspace_tool_call("alpha", "dormant_inspect", {"event_id": "fixture-event"})


def test_legacy_diary_and_checkpoint_never_fall_back_to_another_workspace(runtimes, monkeypatch):
    monkeypatch.setattr(mcp_server, "_session_diary", ["unrelated process diary"])
    assert service.workspace_tool_call("beta", "diary_read", {}) == {"diary": []}
    assert service.workspace_tool_call("alpha", "diary_write", {"entry": "alpha only"})["entries"] == 1
    service.workspace_tool_call("alpha", "session_checkpoint", {"note": "alpha checkpoint"})
    assert service.workspace_tool_call("beta", "diary_read", {}) == {"diary": []}
    assert "alpha only" in str(service.workspace_tool_call("alpha", "diary_read", {}))
    assert mcp_server._session_diary == ["unrelated process diary"]


def test_http_bridge_auth_scope_and_validation(runtimes, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app import main
    from app.db import Base
    from app.models import User, Workspace, WorkspaceApiKey, utc_now
    from app.security import digest_token

    db_engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(db_engine)
    sessions = sessionmaker(bind=db_engine)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    with sessions() as db:
        db.add(User(id="test-owner", github_id="test-owner", login="test-owner"))
        for name in runtimes:
            db.add(Workspace(id=name, slug=name, name=name, schema_name=name, owner_id="test-owner"))
            db.add(WorkspaceApiKey(id=name, workspace_id=name, created_by_user_id="test-owner", label="fixture", token_prefix="fixture", token_hash=digest_token(name + "-test-key")))
        db.commit()
    client = TestClient(main.app)
    endpoint = "/api/workspaces/alpha/mcp"
    body = {"tool": "evidence_list", "args": {"project_id": str(tmp_path / "project")}}
    assert client.post(endpoint, json=body).status_code == 401
    assert client.post(endpoint, json=body, headers={"Authorization": "Bearer beta-test-key"}).status_code == 401
    headers = {"Authorization": "Bearer alpha-test-key"}
    response = client.post(endpoint, json=body, headers=headers)
    assert response.status_code == 200 and response.json()["result"] == []
    response = client.post(endpoint, json={"tool": "dormant_inspect", "args": {}}, headers=headers)
    assert response.status_code == 400
    assert "required" in response.json()["detail"]
    response = client.get("/api/workspaces/alpha/mcp/tools", headers=headers)
    assert next(tool for tool in response.json()["tools"] if tool["name"] == "evidence_put")["inputSchema"]["additionalProperties"] is False
    with sessions() as db:
        key = db.get(WorkspaceApiKey, "alpha")
        key.revoked_at = utc_now()
        db.commit()
    assert client.post(endpoint, json=body, headers=headers).status_code == 401
    db_engine.dispose()


def test_existing_read_tools_execute_against_pinned_store(runtimes):
    calls = {
        "status": {}, "health": {}, "memory_map": {}, "quality_metrics": {},
        "count_by": {"group_by": "layer"}, "access_patterns": {}, "reranker_status": {},
        "recall_recent": {"limit": 2}, "recall_by_type": {"memory_type": "fact"},
        "recall_layer": {"layer": "episodic"}, "recall_timeline": {"start": "2026-01-01"},
        "search_entities": {"query": "fixture"}, "entity_graph": {"name": "fixture"},
        "entity_timeline": {"name": "fixture"}, "backlinks": {"memory_id": "fixture"},
        "export": {"format": "json"}, "session_handoff": {"save": False},
    }
    for name, args in calls.items():
        assert service.workspace_tool_call("alpha", name, args) is not None, name


def test_workspace_index_rebuild_finishes_before_runtime_close(tmp_path, monkeypatch):
    """A missing on-disk ANN index must not leave an unowned daemon at exit."""
    from engram.store import Store
    cfg = Config(db_path=str(tmp_path / "memory.db"))
    cfg.ann.index_path = str(tmp_path / "index")
    cfg.ann.enabled = True
    store = Store(cfg)
    store.init_db()
    store.save_memory(Memory(id="index-fixture", content="local fixture", embedding=np.full(cfg.embedding_dim, 0.1, dtype="float32")))
    store.close()
    def unexpected_worker(*args, **kwargs):
        pytest.fail("workspace startup spawned an unowned ANN worker")
    monkeypatch.setattr(threading.Thread, "start", unexpected_worker)
    server = service.WorkspaceServer(cfg)
    if server.store.ann_index is not None:
        assert server.store.ann_index.ready
    server.store.close()
