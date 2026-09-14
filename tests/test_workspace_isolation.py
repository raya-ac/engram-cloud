"""Authorization regressions with real signed sessions and per-workspace stores."""
import base64
from collections import defaultdict
import json

from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base
from app.models import User, Workspace, WorkspaceApiKey, WorkspaceMember
from app.security import digest_token


@pytest.fixture
def isolated_app(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    rows = defaultdict(list)
    calls = []
    with sessions() as db:
        for name in ("alpha", "beta"):
            db.add(User(id=name, github_id=name, login=name))
            db.add(Workspace(id=name, slug=name, name=name, schema_name=f"ws_{name}", owner_id=name))
            db.add(WorkspaceMember(workspace_id=name, user_id=name, role="owner"))
            db.add(WorkspaceApiKey(id=f"key_{name}", workspace_id=name,
                created_by_user_id=name, label=name, token_prefix=f"engram_{name}",
                token_hash=digest_token(f"engram_{name}_test")))
        db.commit()

    def remember(schema_name, content, layer="episodic", memory_type="narrative"):
        calls.append(("remember", schema_name))
        row = dict(id=f"{schema_name}-{len(rows[schema_name])}", content=content,
            layer=layer, memory_type=memory_type, importance=0.7,
            created_at="2026-09-14T00:00:00")
        rows[schema_name].append(row)
        return {"id": row["id"], "status": "stored"}

    def recent(schema_name, limit=10):
        calls.append(("recent", schema_name))
        return rows[schema_name][-limit:]

    def search(schema_name, query, top_k=8):
        calls.append(("search", schema_name))
        return [{**row, "score": 0.9} for row in rows[schema_name] if query in row["content"]][:top_k]

    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "workspace_remember", remember)
    monkeypatch.setattr(main, "workspace_recent_memories", recent)
    monkeypatch.setattr(main, "workspace_search", search)
    monkeypatch.setattr(main, "workspace_status", lambda schema: {"memories": {"total": len(rows[schema])}})
    client = TestClient(main.app)
    yield client, rows, calls, sessions
    client.close()
    engine.dispose()


def sign_in(client, user_id):
    payload = base64.b64encode(json.dumps({"user_id": user_id}).encode())
    value = TimestampSigner(main.settings.secret_key).sign(payload).decode()
    client.cookies.set("memorylayer_session", value)


def test_workspace_keys_cannot_read_or_write_another_workspace(isolated_app):
    client, rows, calls, sessions = isolated_app
    for name in ("alpha", "beta"):
        headers = {"Authorization": f"Bearer engram_{name}_test"}
        response = client.post(f"/api/workspaces/{name}/remember", headers=headers,
            json={"content": f"private {name} fact"})
        assert response.status_code == 200
        assert response.json()["result"]["status"] == "stored"
    assert rows["ws_alpha"][0]["content"] == "private alpha fact"
    assert rows["ws_beta"][0]["content"] == "private beta fact"

    for owner, target in (("alpha", "beta"), ("beta", "alpha")):
        for headers in ({"Authorization": f"Bearer engram_{owner}_test"},
                        {"X-API-Key": f"engram_{owner}_test"}):
            calls.clear()
            assert client.get(f"/api/workspaces/{target}/memories/recent", headers=headers).status_code == 401
            assert client.post(f"/api/workspaces/{target}/search", headers=headers,
                json={"query": "private"}).status_code == 401
            assert client.post(f"/api/workspaces/{target}/remember", headers=headers,
                json={"content": "cross-workspace overwrite"}).status_code == 401
            assert client.post(f"/api/workspaces/{target}/ingest", headers=headers,
                json={"items": ["cross-workspace import"]}).status_code == 401
            assert calls == [], "Unauthorized request reached an Engram store"
        own = client.post(f"/api/workspaces/{owner}/search",
            headers={"Authorization": f"Bearer engram_{owner}_test"}, json={"query": "private"})
        assert [r["content"] for r in own.json()["results"]] == [f"private {owner} fact"]
    assert {key: len(value) for key, value in rows.items()} == {"ws_alpha": 1, "ws_beta": 1}


def test_signed_browser_session_respects_membership_and_csrf(isolated_app):
    client, rows, calls, _ = isolated_app
    assert client.get("/app", follow_redirects=False).status_code == 302
    sign_in(client, "alpha")
    assert client.get("/app/workspaces/beta").status_code == 403
    assert client.post("/app/workspaces/beta/search", data={"query": "private"}).status_code == 403
    assert client.post("/app/workspaces/beta/remember", data={"content": "forbidden"}).status_code == 403
    assert client.post("/app/workspaces/beta/keys", data={"label": "forbidden"}).status_code == 403
    assert calls == []
    for headers in ({"origin": "https://evil.example"}, {"referer": "https://evil.example/form"}):
        assert client.post("/app/workspaces/alpha/remember", headers=headers,
            data={"content": "forged"}).status_code == 403
    assert calls == []
    assert client.post("/app/workspaces/alpha/remember", headers={"origin": "http://testserver"},
        data={"content": "authorized local fact"}, follow_redirects=False).status_code == 302
    assert rows["ws_alpha"][0]["content"] == "authorized local fact"
    assert "ws_beta" not in rows


@pytest.mark.parametrize("origin", ["https://testserver", "http://testserver:8181", "null", "http://testserver:bad"])
def test_browser_origin_includes_scheme_and_port(isolated_app, origin):
    client, rows, calls, _ = isolated_app
    sign_in(client, "alpha")
    response = client.post("/app/workspaces/alpha/remember", headers={"origin": origin},
        data={"content": "forged from another origin"}, follow_redirects=False)
    assert response.status_code == 403
    assert calls == []


def test_explicit_default_origin_port_is_equivalent(isolated_app):
    client, rows, calls, _ = isolated_app
    sign_in(client, "alpha")
    response = client.post("/app/workspaces/alpha/remember",
        headers={"origin": "http://testserver:80"},
        data={"content": "same origin"}, follow_redirects=False)
    assert response.status_code == 302
    assert rows["ws_alpha"][0]["content"] == "same origin"


def test_configured_https_origin_works_behind_proxy(isolated_app, monkeypatch):
    client, rows, calls, _ = isolated_app
    monkeypatch.setattr(main.settings, "base_url", "https://testserver")
    sign_in(client, "alpha")
    response = client.post("/app/workspaces/alpha/remember",
        headers={"origin": "https://testserver:443"},
        data={"content": "trusted deployment origin"}, follow_redirects=False)
    assert response.status_code == 302
    calls.clear()
    response = client.post("/app/workspaces/alpha/remember",
        headers={"origin": "http://testserver", "x-forwarded-proto": "http"},
        data={"content": "untrusted forwarded origin"}, follow_redirects=False)
    assert response.status_code == 403
    assert calls == []
    assert len(rows["ws_alpha"]) == 1


def test_forwarded_headers_cannot_authorize_another_origin(isolated_app):
    client, rows, calls, _ = isolated_app
    sign_in(client, "alpha")
    response = client.post("/app/workspaces/alpha/remember",
        headers={"origin": "https://evil.example", "x-forwarded-proto": "https",
                 "x-forwarded-host": "evil.example"},
        data={"content": "spoofed origin"}, follow_redirects=False)
    assert response.status_code == 403
    assert calls == []


def test_read_only_member_cannot_write_or_mint_credentials(isolated_app):
    client, rows, calls, sessions = isolated_app
    with sessions() as db:
        db.add(WorkspaceMember(workspace_id="alpha", user_id="beta", role="member"))
        db.commit()
    sign_in(client, "beta")
    assert client.get("/app/workspaces/alpha").status_code == 200
    calls.clear()
    assert client.post("/app/workspaces/alpha/remember", data={"content": "not permitted"}).status_code == 403
    assert client.post("/app/workspaces/alpha/ingest",
        data={"ingest_text": "not permitted", "source_name": "sample"}).status_code == 403
    assert client.post("/app/workspaces/alpha/keys", data={"label": "not permitted"}).status_code == 403
    assert calls == []


def test_revoked_key_and_tampered_session_cannot_access_memory(isolated_app):
    client, rows, calls, sessions = isolated_app
    from app.models import utc_now
    with sessions() as db:
        db.get(WorkspaceApiKey, "key_alpha").revoked_at = utc_now()
        db.commit()
    assert client.get("/api/workspaces/alpha/memories/recent",
        headers={"Authorization": "Bearer engram_alpha_test"}).status_code == 401
    sign_in(client, "alpha")
    cookie = client.cookies.get("memorylayer_session")
    client.cookies.clear()
    client.cookies.set("memorylayer_session", "x" + cookie)
    assert client.get("/app/workspaces/alpha", follow_redirects=False).status_code == 302
    assert calls == []
