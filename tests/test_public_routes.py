from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import app, split_ingest_text


client = TestClient(app)


@app.get("/__test/expired-error", include_in_schema=False)
async def expired_error():
    raise HTTPException(status_code=410, detail="expired")


@app.get("/__test/limited-error", include_in_schema=False)
async def limited_error():
    raise HTTPException(status_code=429, detail="limited")


@app.get("/__test/server-error", include_in_schema=False)
async def server_error():
    raise RuntimeError("boom")


def test_public_service_pages_render():
    for path in (
        "/",
        "/agents",
        "/connect",
        "/architecture",
        "/use-cases",
        "/operations",
        "/integrations",
        "/docs",
        "/capabilities",
        "/examples",
        "/api-explorer",
        "/sdks",
        "/security",
        "/status",
        "/changelog",
    ):
        response = client.get(path)
        assert response.status_code == 200
    connect = client.get("/connect")
    assert "Give an agent a workspace in minutes" in connect.text
    assert "/api/workspaces/{slug}/connect" in connect.text
    docs = client.get("/docs")
    assert "Plug agents into memory" in docs.text
    assert "/api/workspaces/{slug}/connect" in docs.text
    assert "/api/workspaces/{slug}/agent-config" in docs.text
    assert "/api/workspaces/{slug}/observability" in docs.text
    assert "/api/workspaces/{slug}/ingest/preview" in docs.text
    assert "/api/workspaces/{slug}/env" in docs.text
    assert "/api/workspaces/{slug}/usage" in docs.text
    assert "/api/workspaces/{slug}/ingest" in docs.text
    assert "/api/workspaces/{slug}/export/recent" in docs.text
    assert "/api/examples" in docs.text
    assert "recall_context" in docs.text
    assert "session_handoff" in docs.text
    assert "remember_negative" in docs.text
    capabilities = client.get("/capabilities")
    assert "Capability ledger" in capabilities.text
    assert "dream consolidation" in capabilities.text
    sdks = client.get("/sdks")
    assert "JavaScript fetch" in sdks.text
    assert "New agent session" in sdks.text
    api_explorer = client.get("/api-explorer")
    assert "Know the shape before you wire it" in api_explorer.text
    assert "Session checkpoint" in api_explorer.text
    architecture = client.get("/architecture")
    assert "Thin cloud layer" in architecture.text
    assert "Architecture specs" in architecture.text
    assert "Architecture JSON" in architecture.text
    assert "BAAI/bge-small-en-v1.5" in architecture.text
    assert "cross-encoder/ms-marco-MiniLM-L-6-v2" in architecture.text
    assert "Request path" in architecture.text
    status = client.get("/status")
    assert "Readiness checks" in status.text
    assert "/api/service/readiness" in status.text
    assert "/api/service/architecture" in status.text
    use_cases = client.get("/use-cases")
    assert "Memory workflows that survive handoff" in use_cases.text
    assert "Repo continuity" in use_cases.text
    operations = client.get("/operations")
    assert "Operate hosted memory without guessing" in operations.text
    assert "Operator loop" in operations.text
    assert "Deploy path" in operations.text
    assert "Observability contract" in operations.text
    integrations = client.get("/integrations")
    assert "One memory surface for every agent client" in integrations.text
    assert "Connection contract" in integrations.text
    pricing = client.get("/pricing", follow_redirects=False)
    assert pricing.status_code == 302
    assert pricing.headers["location"] == "/docs"


def test_public_service_metadata_routes():
    service_status = client.get("/api/service/status")
    assert service_status.status_code == 200
    assert service_status.json()["service"] == "memorylayer"
    assert service_status.json()["features"] >= 30
    assert service_status.json()["capabilities"] >= 240
    assert service_status.json()["mcp_tools"] >= 50
    assert service_status.json()["tool_groups"] >= 6
    assert service_status.json()["recipes"] >= 10
    assert service_status.json()["sdk_snippets"] >= 6
    assert service_status.json()["playbooks"] >= 5
    assert service_status.json()["api_examples"] >= 14
    assert "runtime_cache" in service_status.json()
    assert service_status.json()["architecture_url"].endswith("/api/service/architecture")
    assert service_status.json()["readiness_url"].endswith("/api/service/readiness")

    manifest = client.get("/api/service/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["version"] == "0.3.0"
    assert manifest.json()["counts"]["capabilities"] >= 240
    assert manifest.json()["routes"]["service_manifest"].endswith("/api/service/manifest")
    assert manifest.json()["routes"]["service_architecture"].endswith("/api/service/architecture")
    assert manifest.json()["routes"]["service_readiness"].endswith("/api/service/readiness")
    assert manifest.json()["routes"]["service_deploy_plan"].endswith("/api/service/deploy-plan")
    assert manifest.json()["routes"]["mcp_manifest"].endswith("/api/mcp/manifest")
    assert manifest.json()["routes"]["api_examples"].endswith("/api/examples")
    assert manifest.json()["routes"]["architecture"].endswith("/architecture")
    assert manifest.json()["routes"]["use_cases"].endswith("/use-cases")
    assert manifest.json()["routes"]["operations"].endswith("/operations")
    assert manifest.json()["routes"]["integrations"].endswith("/integrations")
    assert manifest.json()["routes"]["security"].endswith("/security")
    assert manifest.json()["routes"]["changelog"].endswith("/changelog")
    assert manifest.json()["routes"]["login"].endswith("/login")
    assert manifest.json()["counts"]["routes"] == len(manifest.json()["routes"])

    capabilities = client.get("/api/capabilities")
    assert capabilities.status_code == 200
    assert any(group["name"] == "Discovery APIs" for group in capabilities.json()["capability_groups"])
    assert capabilities.json()["sdk_snippets"]
    assert capabilities.json()["playbooks"]
    assert capabilities.json()["api_examples"]

    mcp_manifest = client.get("/api/mcp/manifest")
    assert mcp_manifest.status_code == 200
    assert mcp_manifest.json()["transport"] == "http-json"
    assert any(group["name"] == "Retrieval" for group in mcp_manifest.json()["tool_groups"])

    service_architecture = client.get("/api/service/architecture")
    assert service_architecture.status_code == 200
    assert service_architecture.json()["service"]["version"] == "0.3.0"
    assert service_architecture.json()["storage"]["workspace_backend"] == "postgres"
    assert service_architecture.json()["models"]["embedding_model"] == "BAAI/bge-small-en-v1.5"
    assert service_architecture.json()["models"]["embedding_dimensions"] == 384
    assert service_architecture.json()["limits"]["max_workspace_runtimes"] == 16
    assert "/api/service/readiness" in service_architecture.json()["surfaces"]["public"]
    assert "/api/workspaces/{slug}/agent-config" in service_architecture.json()["surfaces"]["workspace"]
    assert service_architecture.json()["deployment"]["scripts"]["deploy"] == "scripts/deploy.sh"

    service_readiness = client.get("/api/service/readiness")
    assert service_readiness.status_code in (200, 503)
    readiness_payload = service_readiness.json()
    assert readiness_payload["status"] in ("ok", "degraded")
    assert any(check["name"] == "database" for check in readiness_payload["checks"])
    assert any(check["name"] == "runtime_cache" for check in readiness_payload["checks"])

    deploy_plan = client.get("/api/service/deploy-plan")
    assert deploy_plan.status_code == 200
    assert deploy_plan.json()["version"] == "0.3.0"
    assert deploy_plan.json()["deployment"]["scripts"]["live_check"] == "scripts/live-check.sh"

    snippets = client.get("/api/sdk-snippets")
    assert snippets.status_code == 200
    assert any(snippet["language"] == "python" for snippet in snippets.json()["sdk_snippets"])

    playbooks = client.get("/api/playbooks")
    assert playbooks.status_code == 200
    assert any(playbook["name"] == "Memory cleanup" for playbook in playbooks.json()["playbooks"])

    api_examples = client.get("/api/examples")
    assert api_examples.status_code == 200
    assert any(example["name"] == "Recall context" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Connection kit" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Service architecture" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Service readiness" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Agent config bundle" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Ingest preview" for example in api_examples.json()["api_examples"])
    assert any(example["name"] == "Observability" for example in api_examples.json()["api_examples"])
    assert any(example["path"] == "/api/workspaces/{slug}/ingest" for example in api_examples.json()["api_examples"])

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "/api/mcp/manifest" in sitemap.text
    assert "/api/service/architecture" in sitemap.text
    assert "/api/service/readiness" in sitemap.text
    assert "/api/service/deploy-plan" in sitemap.text
    assert "/api/sdk-snippets" in sitemap.text
    assert "/api/examples" in sitemap.text
    assert "/api-explorer" in sitemap.text
    assert "/connect" in sitemap.text
    assert "/sdks" in sitemap.text
    assert "/capabilities" in sitemap.text
    assert "/examples" in sitemap.text
    assert "/security" in sitemap.text
    assert "/architecture" in sitemap.text
    assert "/use-cases" in sitemap.text
    assert "/operations" in sitemap.text
    assert "/integrations" in sitemap.text


def test_skills_endpoints_expose_json_and_markdown():
    index = client.get("/api/skills")
    assert index.status_code == 200
    payload = index.json()
    assert "skills" in payload
    assert any(skill["name"] == "workspace-memory" for skill in payload["skills"])

    skill_json = client.get("/api/skills/workspace-memory")
    assert skill_json.status_code == 200
    assert skill_json.json()["name"] == "workspace-memory"

    skill_md = client.get("/api/skills/workspace-memory.md")
    assert skill_md.status_code == 200
    assert "# Workspace Memory" in skill_md.text


def test_error_pages_use_public_theme_but_api_stays_json():
    missing = client.get("/definitely-missing")
    assert missing.status_code == 404
    assert "Memory has no path here." in missing.text
    assert "Return home" in missing.text

    api_missing = client.get("/api/definitely-missing")
    assert api_missing.status_code == 404
    assert api_missing.json()["detail"] == "Not found"

    bad_request = client.get("/%2e%2e/%2e%2e/etc/passwd")
    assert bad_request.status_code == 400
    assert "This signal is malformed." in bad_request.text

    forbidden = client.post(
        "/app/workspaces",
        data={"name": "cross site"},
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )
    assert forbidden.status_code == 403
    assert "This boundary held." in forbidden.text

    method_blocked = client.request("TRACE", "/")
    assert method_blocked.status_code == 405
    assert "Wrong motion for this route." in method_blocked.text

    too_large = client.post(
        "/app/workspaces",
        data={"name": "x"},
        headers={"content-length": "999999999"},
        follow_redirects=False,
    )
    assert too_large.status_code == 413
    assert "Too much memory at once." in too_large.text

    expired = client.get("/__test/expired-error")
    assert expired.status_code == 410
    assert "This link aged out." in expired.text

    limited = client.get("/__test/limited-error")
    assert limited.status_code == 429
    assert "The channel is saturated." in limited.text

    server = TestClient(app, raise_server_exceptions=False).get("/__test/server-error")
    assert server.status_code == 500
    assert "The runtime dropped a frame." in server.text


def test_ingest_text_split_modes():
    assert split_ingest_text("one\n\ntwo", mode="paragraphs") == ["one", "two"]
    assert split_ingest_text("- one\n- two", mode="lines") == ["one", "two"]
    assert split_ingest_text('{"items":["one","two"]}', mode="json") == ["one", "two"]
    assert split_ingest_text("# One\nalpha\n# Two\nbeta", mode="markdown") == ["# One\nalpha", "# Two\nbeta"]
    assert split_ingest_text("name,value\nalpha,1\nbeta,2", mode="csv") == [
        '{"name": "alpha", "value": "1"}',
        '{"name": "beta", "value": "2"}',
    ]
