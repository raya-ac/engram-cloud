from fastapi.testclient import TestClient

from app.main import app, split_ingest_text


client = TestClient(app)


def test_public_service_pages_render():
    for path in ("/", "/agents", "/connect", "/docs", "/capabilities", "/examples", "/api-explorer", "/sdks", "/security", "/status", "/changelog"):
        response = client.get(path)
        assert response.status_code == 200
    connect = client.get("/connect")
    assert "Give an agent a workspace in minutes" in connect.text
    assert "/api/workspaces/{slug}/connect" in connect.text
    docs = client.get("/docs")
    assert "Plug agents into memory" in docs.text
    assert "/api/workspaces/{slug}/connect" in docs.text
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
    assert service_status.json()["api_examples"] >= 12
    assert "runtime_cache" in service_status.json()

    manifest = client.get("/api/service/manifest")
    assert manifest.status_code == 200
    assert manifest.json()["counts"]["capabilities"] >= 240
    assert manifest.json()["routes"]["mcp_manifest"].endswith("/api/mcp/manifest")
    assert manifest.json()["routes"]["api_examples"].endswith("/api/examples")

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
    assert any(example["path"] == "/api/workspaces/{slug}/ingest" for example in api_examples.json()["api_examples"])

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
    assert "/api/mcp/manifest" in sitemap.text
    assert "/api/sdk-snippets" in sitemap.text
    assert "/api/examples" in sitemap.text
    assert "/api-explorer" in sitemap.text
    assert "/connect" in sitemap.text
    assert "/sdks" in sitemap.text
    assert "/capabilities" in sitemap.text
    assert "/examples" in sitemap.text
    assert "/security" in sitemap.text


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


def test_ingest_text_split_modes():
    assert split_ingest_text("one\n\ntwo", mode="paragraphs") == ["one", "two"]
    assert split_ingest_text("- one\n- two", mode="lines") == ["one", "two"]
    assert split_ingest_text('{"items":["one","two"]}', mode="json") == ["one", "two"]
