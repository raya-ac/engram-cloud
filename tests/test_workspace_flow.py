import re

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import auth
from app import main
from app.db import Base
from app.models import AuditEvent, User, Workspace, WorkspaceApiEvent, WorkspaceIngestRun, WorkspaceMember


def test_authenticated_workspace_lifecycle(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)

    auth_state = {"user_id": "owner-user"}
    db = TestingSessionLocal()
    db.add_all(
        [
            User(id="owner-user", github_id="1", login="owner", name="Owner"),
            User(id="member-user", github_id="2", login="member", name="Member"),
        ]
    )
    db.commit()
    db.close()

    memory_rows: list[dict] = []

    def fake_init_workspace_store(schema_name):
        return None

    def fake_status(schema_name):
        return {
            "memories": {"total": len(memory_rows)},
            "entities": 2,
            "relationships": 1,
            "db_size_mb": 0,
        }

    def fake_recent(schema_name, limit=10):
        return list(reversed(memory_rows))[:limit]

    def fake_remember(schema_name, content, layer="episodic", memory_type="narrative"):
        memory = {
            "id": f"mem-{len(memory_rows) + 1}",
            "content": content,
            "layer": layer,
            "memory_type": memory_type,
            "importance": 0.7,
            "created_at": "2026-04-24T00:00:00",
        }
        memory_rows.append(memory)
        return {"id": memory["id"], "status": "stored"}

    def fake_search(schema_name, query, top_k=8):
        return [
            {
                "id": row["id"],
                "content": row["content"],
                "layer": row["layer"],
                "memory_type": row["memory_type"],
                "score": 0.91,
            }
            for row in memory_rows
            if query.lower() in row["content"].lower()
        ][:top_k]

    def fake_tool_call(schema_name, tool_name, args=None):
        if tool_name == "recall_recent":
            return fake_recent(schema_name, limit=(args or {}).get("limit", 5))
        return {"tool": tool_name, "args": args or {}}

    monkeypatch.setattr(main, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "init_workspace_store", fake_init_workspace_store)
    monkeypatch.setattr(main, "workspace_status", fake_status)
    monkeypatch.setattr(main, "workspace_recent_memories", fake_recent)
    monkeypatch.setattr(main, "workspace_remember", fake_remember)
    monkeypatch.setattr(main, "workspace_search", fake_search)
    monkeypatch.setattr(main, "workspace_tool_call", fake_tool_call)
    monkeypatch.setattr(main, "current_user_id", lambda request: auth_state["user_id"])
    monkeypatch.setattr(auth, "current_user_id", lambda request: auth_state["user_id"])

    client = TestClient(main.app)

    response = client.get("/app", follow_redirects=False)
    assert response.status_code == 200
    assert "Your workspaces" in response.text

    response = client.post("/app/workspaces", data={"name": "Flow Test"}, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "/app/workspaces/flow-test"

    response = client.get("/app/workspaces/flow-test")
    assert response.status_code == 200
    assert "Ingest data" in response.text
    assert "Workspace setup checklist" in response.text
    assert "Agent config" in response.text
    assert "Ingest preview API" in response.text
    assert "Slowest recent routes" in response.text

    response = client.post(
        "/app/workspaces/flow-test/remember",
        data={"content": "alpha launch note", "layer": "semantic", "memory_type": "fact"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert memory_rows[-1]["content"] == "alpha launch note"

    response = client.post(
        "/app/workspaces/flow-test/search",
        data={"query": "alpha"},
    )
    assert response.status_code == 200
    assert "alpha launch note" in response.text

    response = client.post(
        "/app/workspaces/flow-test/ingest",
        data={
            "source_name": "notes.md",
            "source_type": "handoff",
            "ingest_text": "beta item\n\ngamma item",
            "split_mode": "paragraphs",
            "layer": "episodic",
            "memory_type": "fact",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert [row["content"] for row in memory_rows[-2:]] == ["beta item", "gamma item"]

    response = client.post("/app/workspaces/flow-test/keys", data={"label": "agent"}, follow_redirects=True)
    assert response.status_code == 200
    token_match = re.search(r"engram_[A-Za-z0-9_-]+", response.text)
    assert token_match
    api_token = token_match.group(0)
    headers = {"Authorization": f"Bearer {api_token}"}

    assert client.get("/api/workspaces/flow-test/status", headers=headers).status_code == 200
    assert client.get("/api/workspaces/flow-test/memories/recent", headers=headers).json()["memories"]

    response = client.post(
        "/api/workspaces/flow-test/remember",
        headers=headers,
        json={"content": "delta api fact", "layer": "semantic", "memory_type": "fact"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["status"] == "stored"

    response = client.post(
        "/api/workspaces/flow-test/search",
        headers={**headers, "Content-Type": "application/json"},
        content="{bad json",
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid JSON body"

    response = client.post(
        "/api/workspaces/flow-test/ingest",
        headers=headers,
        json={"source_name": "api.json", "items": ["epsilon", "zeta"], "memory_type": "fact"},
    )
    assert response.status_code == 200
    assert response.json()["ingest"]["item_count"] == 2

    assert client.post(
        "/api/workspaces/flow-test/search",
        headers=headers,
        json={"query": "delta", "top_k": 5},
    ).json()["results"][0]["content"] == "delta api fact"
    assert client.get("/api/workspaces/flow-test/ingest/runs", headers=headers).json()["runs"]
    assert client.get("/api/workspaces/flow-test/export/recent", headers=headers).json()["memories"]
    bootstrap_payload = client.get("/api/workspaces/flow-test/bootstrap", headers=headers).json()
    assert "ingest_url" in bootstrap_payload["api"]
    assert "ingest_preview_url" in bootstrap_payload["api"]
    assert "observability_url" in bootstrap_payload["api"]
    assert "agent_config_url" in bootstrap_payload["api"]
    assert "connect_config_url" in bootstrap_payload["api"]
    connect_payload = client.get("/api/workspaces/flow-test/connect", headers=headers).json()
    assert connect_payload["workspace"]["slug"] == "flow-test"
    assert connect_payload["endpoints"]["mcp"].endswith("/api/workspaces/flow-test/mcp")
    assert connect_payload["client_profiles"]["agent_config_url"].endswith("/api/workspaces/flow-test/agent-config")
    assert connect_payload["startup_calls"]
    agent_config = client.get("/api/workspaces/flow-test/agent-config", headers=headers).json()
    assert "codex_toml" in agent_config
    assert "claude_skill" in agent_config
    assert agent_config["endpoints"]["observability"].endswith("/api/workspaces/flow-test/observability")
    assert client.get("/api/workspaces/flow-test/codex.toml", headers=headers).text.startswith("# Memorylayer workspace profile")
    assert "# Memorylayer workspace: Flow Test" in client.get("/api/workspaces/flow-test/claude-skill.md", headers=headers).text
    env_payload = client.get("/api/workspaces/flow-test/env", headers=headers)
    assert env_payload.status_code == 200
    assert 'MEMORYLAYER_WORKSPACE="flow-test"' in env_payload.text
    preview_payload = client.post(
        "/api/workspaces/flow-test/ingest/preview",
        headers=headers,
        json={"content": "# One\nalpha\n# Two\nbeta", "split_mode": "markdown"},
    ).json()
    assert preview_payload["ingest_preview"]["item_count"] == 2
    assert client.post(
        "/api/workspaces/flow-test/mcp",
        headers=headers,
        json={"tool": "recall_recent", "args": {"limit": 2}},
    ).json()["result"]
    tools_payload = client.get("/api/workspaces/flow-test/mcp/tools", headers=headers).json()
    tool_names = {tool["name"] for tool in tools_payload["tools"]}
    assert {"recall_context", "session_handoff", "remember_negative", "get_skills"}.issubset(tool_names)
    assert next(tool for tool in tools_payload["tools"] if tool["name"] == "recall_context")["args"]["query"] == "string"
    assert client.get("/api/workspaces/flow-test/usage", headers=headers).json()["summary"]["total_calls"] >= 7
    observability = client.get("/api/workspaces/flow-test/observability", headers=headers).json()
    assert "p95_duration_ms" in observability["observability"]
    assert observability["observability"]["sample_size"] >= 1
    assert client.get("/api/workspaces/flow-test/audit", headers=headers).json()["events"]

    response = client.post(
        "/app/workspaces/flow-test/invites",
        data={"email": "member@example.com", "role": "member"},
        follow_redirects=True,
    )
    assert response.status_code == 200
    invite_match = re.search(r"engraminvite_[A-Za-z0-9_-]+", response.text)
    assert invite_match
    invite_token = invite_match.group(0)

    auth_state["user_id"] = "member-user"
    assert client.get(f"/app/invites/{invite_token}").status_code == 200
    response = client.post(f"/app/invites/{invite_token}/accept", follow_redirects=False)
    assert response.status_code == 302

    db = TestingSessionLocal()
    try:
        workspace = db.execute(select(Workspace).where(Workspace.slug == "flow-test")).scalar_one()
        assert db.execute(select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)).scalars().all()
        assert db.execute(select(WorkspaceIngestRun).where(WorkspaceIngestRun.workspace_id == workspace.id)).scalars().all()
        assert db.execute(select(WorkspaceApiEvent).where(WorkspaceApiEvent.workspace_id == workspace.id)).scalars().all()
        assert db.execute(
            select(WorkspaceApiEvent).where(
                WorkspaceApiEvent.workspace_id == workspace.id,
                WorkspaceApiEvent.route == "/search",
                WorkspaceApiEvent.status_code == 400,
            )
        ).scalar_one()
        assert db.execute(select(AuditEvent).where(AuditEvent.workspace_id == workspace.id)).scalars().all()
    finally:
        db.close()
        client.close()
        engine.dispose()
