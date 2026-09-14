"""Hosted cognition HTTP authorization, tenant dispatch, and input boundaries."""
import json

import pytest
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app import main
from app.models import AuditEvent, WorkspaceMember
from test_workspace_isolation import isolated_app, sign_in
from test_mythic_service import isolated as cognition_stores


@pytest.fixture
def cognition_app(isolated_app, monkeypatch):
    client, rows, memory_calls, sessions = isolated_app
    calls = []

    def dispatch(schema_name, operation, params=None):
        calls.append((schema_name, operation, params))
        if operation == "settings_get":
            return {"enabled": True}
        if operation in {"session_list", "events"}:
            return []
        return {"schema": schema_name, "operation": operation, "enabled": True}

    monkeypatch.setattr(main, "mythic_dispatch", dispatch)
    original_render = main.render
    monkeypatch.setattr(main, "render", lambda request, template, **context:
        HTMLResponse("Cognition authorization fixture") if template == "cognition.html"
        else original_render(request, template, **context))
    yield client, calls, sessions


def api_headers(name="alpha"):
    return {"Authorization": f"Bearer engram_{name}_test"}


def action(operation="session_start", **params):
    return {"operation": operation, "params_json": json.dumps({"project_id": "project", **params})}


def test_mythic_api_requires_workspace_key_even_with_browser_session(cognition_app):
    client, calls, _ = cognition_app
    sign_in(client, "alpha")
    assert client.get("/api/workspaces/alpha/mythic").status_code == 401
    assert client.post("/api/workspaces/alpha/mythic",
        json={"operation": "session_start", "params": {"project_id": "project", "goal": "private"}}).status_code == 401
    assert calls == []


@pytest.mark.parametrize("owner,target", [("alpha", "beta"), ("beta", "alpha")])
def test_mythic_key_cannot_access_another_workspace(cognition_app, owner, target):
    client, calls, _ = cognition_app
    for headers in (api_headers(owner), {"X-API-Key": f"engram_{owner}_test"}):
        assert client.get(f"/api/workspaces/{target}/mythic", headers=headers).status_code == 401
        for operation in ("session_start", "session_list", "settings_update"):
            assert client.post(f"/api/workspaces/{target}/mythic", headers=headers,
                json={"operation": operation, "params": {"project_id": "project"}}).status_code == 401
        assert client.post(f"/api/workspaces/{target}/mcp", headers=headers,
            json={"tool": "mythic_session_start", "args": {"project_id": "project", "goal": "private"}}).status_code == 401
    assert calls == []


@pytest.mark.parametrize("name", ["alpha", "beta"])
def test_mythic_dispatch_uses_authenticated_workspace_schema(cognition_app, name):
    client, calls, sessions = cognition_app
    params = {"project_id": "project", "goal": f"{name} private goal"}
    response = client.post(f"/api/workspaces/{name}/mythic", headers=api_headers(name),
        json={"operation": "session_start", "params": params})
    assert response.status_code == 200
    assert calls == [(f"ws_{name}", "session_start", params)]
    assert response.json()["result"]["schema"] == f"ws_{name}"
    with sessions() as db:
        event = db.execute(select(AuditEvent)).scalar_one()
        assert (event.workspace_id, event.event_type, event.actor_user_id) == (name, "mythic.operation", None)


def test_mythic_browser_routes_require_membership_and_reject_csrf(cognition_app):
    client, calls, _ = cognition_app
    assert client.get("/app/workspaces/alpha/cognition", follow_redirects=False).status_code == 302
    sign_in(client, "alpha")
    assert client.get("/app/workspaces/beta/cognition").status_code == 403
    assert client.post("/app/workspaces/beta/cognition/action",
        data=action(goal="private"), follow_redirects=False).status_code == 403
    assert client.post("/app/workspaces/alpha/cognition/action",
        data=action(goal="forged"), headers={"origin": "https://evil.example"}).status_code == 403
    assert calls == []


@pytest.mark.parametrize("role", ["member", "editor", "admin"])
def test_mythic_roles_separate_read_write_and_settings(cognition_app, role):
    client, calls, sessions = cognition_app
    with sessions() as db:
        db.add(WorkspaceMember(workspace_id="alpha", user_id="beta", role=role))
        db.commit()
    sign_in(client, "beta")
    assert client.get("/app/workspaces/alpha/cognition").status_code == 200
    assert all(operation in main.MYTHIC_READ_OPERATIONS for _, operation, _ in calls)
    calls.clear()
    response = client.post("/app/workspaces/alpha/cognition/action",
        data=action(goal="authorized according to role"), follow_redirects=False)
    assert response.status_code == (403 if role == "member" else 200)
    if role == "member":
        assert calls == []
    else:
        assert calls[0][0:2] == ("ws_alpha", "session_start")
        with sessions() as db:
            event = db.execute(select(AuditEvent)).scalar_one()
            assert (event.workspace_id, event.event_type, event.actor_user_id) == ("alpha", "mythic.operation", "beta")
    calls.clear()
    response = client.post("/app/workspaces/alpha/cognition/action",
        data=action("settings_update", enabled=False), follow_redirects=False)
    assert response.status_code == (200 if role == "admin" else 403)
    if role != "admin":
        assert calls == []
    else:
        assert calls[0] == ("ws_alpha", "settings_update", {"project_id": "project", "enabled": False})
    calls.clear()
    response = client.post("/app/workspaces/alpha/cognition/settings",
        data={"project_id": "project", "enabled": "on"}, follow_redirects=False)
    assert response.status_code == (302 if role == "admin" else 403)
    assert calls == ([("ws_alpha", "settings_update", {"project_id": "project", "enabled": True})]
                     if role == "admin" else [])


@pytest.mark.parametrize("payload", [[], {"operation": "status", "params": []},
    {"operation": "status", "params": "invalid"}, {"operation": None},
    {"operation": 17}, {"operation": {"untrusted": "value"}}])
def test_mythic_api_rejects_malformed_envelopes(cognition_app, payload):
    client, calls, _ = cognition_app
    assert client.post("/api/workspaces/alpha/mythic", headers=api_headers(), json=payload).status_code == 400
    assert calls == []


@pytest.mark.parametrize("form", [
    {"operation": "session_start", "params_json": "not json"},
    {"operation": "session_start", "params_json": "[]"},
    {"operation": "session_cycle", "project_id": "project", "session_id": "session", "top_k": "not-a-number"},
])
def test_mythic_browser_rejects_malformed_form_before_dispatch(cognition_app, form):
    client, calls, _ = cognition_app
    sign_in(client, "alpha")
    assert client.post("/app/workspaces/alpha/cognition/action", data=form).status_code == 400
    assert calls == []


@pytest.mark.parametrize("operation,params", [
    ("session_start", {"project_id": "../outside", "goal": "invalid project"}),
    ("session_start", {"project_id": "/etc", "goal": "invalid project"}),
    ("assumption_check", {"project_id": "project", "session_id": "session", "assumption_id": "assumption",
                          "check_type": "file_exists", "parameters": {"path": "/etc/passwd"}}),
    ("session_cycle", {"project_id": "project", "session_id": "session", "publish": True}),
    ("session_start", {"project_id": "project", "goal": "invalid tenant override", "schema_name": "ws_beta"}),
])
@pytest.mark.parametrize("transport", ["mythic", "mcp"])
def test_mythic_invalid_host_or_tenant_payload_never_reaches_runtime(isolated_app, monkeypatch, operation, params, transport):
    from app import mythic_service
    client, _, _, _ = isolated_app
    monkeypatch.setattr(mythic_service, "workspace_runtime", lambda *_: pytest.fail("invalid payload accessed Engram"))
    monkeypatch.setattr(mythic_service, "_paths", lambda *_: pytest.fail("invalid payload accessed storage"))
    payload = ({"operation": operation, "params": params} if transport == "mythic"
               else {"tool": f"mythic_{operation}", "args": params})
    response = client.post(f"/api/workspaces/alpha/{transport}", headers=api_headers(), json=payload)
    assert response.status_code == 400
    assert "/etc/passwd" not in response.text
    assert "../outside" not in response.text


@pytest.mark.parametrize("transport", ["mythic", "mcp"])
def test_real_http_cycle_evidence_and_resume_stay_inside_tenant(isolated_app, cognition_stores, transport):
    from engram.store import Memory
    client, _, _, _ = isolated_app
    for name in ("alpha", "beta"):
        cognition_stores[f"ws_{name}"].store.save_memory(Memory(
            id=f"{name}-private-context", content=f"postgres release {name} private context", layer="semantic"))

    def call(operation, name="alpha", **params):
        params = {"project_id": "release", **params}
        body = ({"operation": operation, "params": params} if transport == "mythic"
                else {"tool": f"mythic_{operation}", "args": params})
        response = client.post(f"/api/workspaces/{name}/{transport}", headers=api_headers(name), json=body)
        assert response.status_code == 200, response.text
        assert response.json()["workspace"] == name
        return response.json()["result"]

    session = call("session_start", goal="postgres release")["session"]["id"]
    call("task_add", session_id=session, title="Check release capability")
    cycle = call("session_cycle", session_id=session)
    assert "alpha-private-context" in json.dumps(cycle)
    assert "beta-private-context" not in json.dumps(cycle)
    assert cycle["bridge_result"] is None
    assumption = call("assumption_create", session_id=session,
        statement="Release capability is available", decision="release", impact=3)
    observation = call("assumption_check", session_id=session, assumption_id=assumption["id"],
        check_type="engram_tool_available", parameters={"tool": "fictional-missing-release-tool"})
    assert observation["state"] == "contradicted"
    assert observation["decision_revision"]["disposition"] == "revise"
    assert observation["decision_revision"]["executes_action"] is False
    receipt = call("assumption_publish_evidence", session_id=session,
        assumption_id=assumption["id"], evidence_id=observation["id"])
    assert receipt["verified_by_engram"] is False
    evidence = call("assumption_evidence_get", session_id=session,
        assumption_id=assumption["id"], evidence_id=observation["id"])
    assert evidence["state"] == "contradicted"
    assert call("session_snapshot", session_id=session)["recent_cycles"]
    assert call("session_list", name="beta") == []
    foreign_params = {"project_id": "release", "session_id": session}
    foreign_body = ({"operation": "session_snapshot", "params": foreign_params} if transport == "mythic"
                    else {"tool": "mythic_session_snapshot", "args": foreign_params})
    foreign = client.post(f"/api/workspaces/beta/{transport}", headers=api_headers("beta"), json=foreign_body)
    assert foreign.status_code == 404
    assert "alpha-private-context" not in foreign.text
    assert cognition_stores["ws_beta"].store.get_memory(receipt["id"]) is None
    cognition_stores["ws_alpha"].store.forget_memory(receipt["id"])
    assert call("assumption_evidence_get", session_id=session, assumption_id=assumption["id"],
                evidence_id=observation["id"])["reason"] == "forgotten"
    assert call("settings_update", enabled=False) == {"enabled": False}
    assert call("settings_get", name="beta") == {"enabled": True}


def test_discovery_advertises_actual_hosted_operations(cognition_app):
    from app.mythic_service import PUBLIC_MYTHIC_TOOLS
    client, calls, _ = cognition_app
    discovery = client.get("/api/workspaces/alpha/mythic", headers=api_headers())
    assert discovery.status_code == 200
    payload = discovery.json()
    names = {tool["name"] for tool in payload["tools"]["tools"]}
    assert names == {tool["name"] for tool in PUBLIC_MYTHIC_TOOLS}
    assert payload["tools"]["host_execution"] is False
    advertised = client.get("/api/workspaces/alpha/mcp/tools", headers=api_headers())
    assert advertised.status_code == 200
    adapter_names = {tool["name"] for tool in advertised.json()["tools"] if tool["name"].startswith("mythic_")}
    assert adapter_names == {f"mythic_{name}" for name in names}
