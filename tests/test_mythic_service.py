"""Real hosted Mythic contracts with disposable Engram stores and no models."""
import json
import os
import threading
import time
from types import SimpleNamespace
import uuid

import pytest
from engram.config import Config
from engram.store import Memory, Store
from app import mythic_service as hosted


@pytest.fixture(params=["sqlite", "postgres"])
def isolated(request, tmp_path, monkeypatch):
    dsn = os.environ.get("ENGRAM_TEST_POSTGRES_DSN")
    if request.param == "postgres" and not dsn:
        pytest.skip("Set a disposable ENGRAM_TEST_POSTGRES_DSN")
    monkeypatch.setattr(hosted.settings, "data_dir", tmp_path / "data")
    runtimes = {}
    schemas = []
    for name in ("ws_alpha", "ws_beta"):
        cfg = Config(db_path=str(tmp_path / name / "engram.db"))
        cfg.ann.enabled = False
        if request.param == "postgres":
            import psycopg
            from psycopg.conninfo import make_conninfo
            schema = "mythic_test_" + uuid.uuid4().hex
            schemas.append(schema)
            with psycopg.connect(dsn, autocommit=True) as conn:
                conn.execute(f'CREATE SCHEMA "{schema}"')
            cfg.storage_backend = "postgres"
            cfg.postgres_dsn = make_conninfo(dsn, options=f"-c search_path={schema}")
        store = Store(cfg)
        store.init_db()
        runtimes[name] = SimpleNamespace(config=cfg, store=store, lock=threading.RLock())
    monkeypatch.setattr(hosted, "workspace_runtime", runtimes.__getitem__)
    yield runtimes
    for runtime in runtimes.values():
        runtime.store.close()
    if schemas:
        with psycopg.connect(dsn, autocommit=True) as conn:
            for schema in schemas:
                conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def call(op, *, workspace="ws_alpha", project="project-a", **params):
    return hosted.mythic_dispatch(workspace, op, {"project_id": project, **params})


def test_real_contradiction_revision_evidence_and_fresh_service_resume(isolated):
    session = call("session_start", goal="postgres deployment")['session']['id']
    task = call("task_add", session_id=session, title="check release availability")
    assert task['session']['id'] == session
    premise = call("assumption_create", session_id=session, statement="Required release tool is available", decision="release", impact=3)
    assert premise["state"] == "unknown"
    observation = call("assumption_check", session_id=session, assumption_id=premise["id"], check_type="engram_tool_available", parameters={"tool": "fixture-missing-release-tool"})
    assert observation["state"] == "contradicted"
    assert observation["decision_revision"]["disposition"] == "revise"
    assert observation["decision_revision"]["executes_action"] is False
    receipt = call("assumption_publish_evidence", session_id=session, assumption_id=premise["id"], evidence_id=observation["id"])
    assert receipt["verified_by_engram"] is False
    read = call("assumption_evidence_get", session_id=session, assumption_id=premise["id"], evidence_id=observation["id"])
    assert read["state"] == "contradicted"
    assert read["project_id"] == "project-a"
    assert "fixture-missing-release-tool" in str(read["observation"])
    # Each dispatch opens and closes a fresh standalone MythicService.
    resumed = call("assumption_inspect", session_id=session)
    assert resumed["assumptions"][0]["state"] == "contradicted"
    assert resumed["decisions"][-1]["disposition"] == "revise"
    assert call("session_snapshot", session_id=session)["session"]["id"] == session
    assert call("session_list", workspace="ws_beta") == []
    assert call("session_list", project="other-project") == []
    with pytest.raises(FileNotFoundError):
        call("assumption_inspect", workspace="ws_beta", session_id=session)
    with pytest.raises(FileNotFoundError):
        call("assumption_inspect", project="other-project", session_id=session)
    assert isolated["ws_beta"].store.get_memory(receipt["id"]) is None
    isolated["ws_alpha"].store.forget_memory(receipt["id"])
    assert call("assumption_evidence_get", session_id=session, assumption_id=premise["id"], evidence_id=observation["id"])["reason"] == "forgotten"


def test_cycles_use_workspace_context_without_reinforcement_or_execution(isolated, monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: pytest.fail("host execution attempted"))
    alpha = isolated["ws_alpha"].store
    alpha.save_memory(Memory(id="alpha-context", content="postgres deployment rollback", layer="semantic"))
    isolated["ws_beta"].store.save_memory(Memory(id="beta-context", content="postgres deployment secret other tenant", layer="semantic"))
    before = dict(alpha.conn.execute("SELECT * FROM memories WHERE id=?", ("alpha-context",)).fetchone())
    session = call("session_start", goal="postgres deployment")['session']['id']
    cycle = call("session_cycle", session_id=session, top_k=5)
    encoded = json.dumps(cycle)
    assert "alpha-context" in encoded
    assert "beta-context" not in encoded
    assert cycle["bridge_result"] is None
    assert dict(alpha.conn.execute("SELECT * FROM memories WHERE id=?", ("alpha-context",)).fetchone()) == before
    assert call("session_snapshot", session_id=session)["recent_cycles"]
    status = call("status")
    assert status["engram"]["connected"] is True
    assert status["host_execution"] is False
    assert status["enabled"] is True
    assert "store" not in status and "pid" not in status
    assert str(hosted.settings.data_dir) not in json.dumps(status)


def test_enabled_setting_persists_and_gates_real_mutations(isolated):
    session = call("session_start", goal="fixture session")['session']['id']
    assert call("settings_update", enabled=False) == {"enabled": False}
    assert call("settings_get", project="another") == {"enabled": False}
    assert call("settings_get", workspace="ws_beta") == {"enabled": True}
    assert call("session_list")[0]["id"] == session
    with pytest.raises(ValueError, match="disabled"):
        call("session_cycle", session_id=session)
    assert call("settings_update", enabled=True)["enabled"] is True
    assert call("session_cycle", session_id=session)["session"]["id"] == session


@pytest.mark.parametrize("operation,params", [
    ("session_start", {"project_id": "../../outside", "goal": "a"}),
    ("session_start", {"project_id": "/etc", "goal": "a"}),
    ("session_start", {"project_id": "okay", "goal": "x" * 2001}),
    ("session_cycle", {"project_id": "okay", "session_id": "abc", "publish": True}),
    ("assumption_check", {"project_id": "okay", "session_id": "abc", "assumption_id": "abc", "check_type": "project_file_exists", "parameters": {"path": "/etc/passwd"}}),
    ("plugin_run", {"project_id": "okay", "command": "do not execute"}),
    ("assumption_create", {"project_id": "okay", "session_id": "abc", "statement": "a", "decision": "b", "max_age_seconds": float("nan")}),
])
def test_dangerous_or_unbounded_inputs_rejected_before_runtime(operation, params, monkeypatch, tmp_path):
    monkeypatch.setattr(hosted.settings, "data_dir", tmp_path / "untouched")
    monkeypatch.setattr(hosted, "MythicService", lambda *args: pytest.fail("invalid call started runtime"))
    with pytest.raises(ValueError):
        hosted.mythic_dispatch("ws_alpha", operation, params)
    assert not hosted.settings.data_dir.exists()


def test_capacity_limit_and_concurrent_session_claim(isolated, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    monkeypatch.setattr(hosted, "MAX_SESSIONS", 2)
    with ThreadPoolExecutor(max_workers=2) as executor:
        sessions = list(executor.map(lambda n: call("session_start", goal=f"session {n}"), range(2)))
    assert len({row["session"]["id"] for row in sessions}) == 2
    with pytest.raises(ValueError, match="session limit"):
        call("session_start", goal="third")
    assert len(call("session_list")) == 2


def test_status_checks_become_unknown_on_failure_without_exposing_error(isolated, monkeypatch):
    session = call("session_start", goal="connection check")['session']['id']
    premise = call("assumption_create", session_id=session, statement="Engram responds", decision="continue")
    args = {"session_id": session, "assumption_id": premise["id"], "check_type": "engram_status", "parameters": {}}
    observed = call("assumption_check", **args)
    assert observed["state"] == "supported"
    original = hosted.WorkspaceEngramClient.call_tool
    def timeout(client, operation, params):
        if operation == "status":
            raise TimeoutError("private server path and token must stay hidden")
        return original(client, operation, params)
    monkeypatch.setattr(hosted.WorkspaceEngramClient, "call_tool", timeout)
    failed = call("assumption_check", **args)
    assert failed["state"] == "unknown" and failed["timed_out"] is True
    assert failed["decision_revision"]["disposition"] == "hold"
    assert "private server" not in json.dumps(failed)
    assert call("assumption_inspect", session_id=session)["assumptions"][0]["state"] == "unknown"
