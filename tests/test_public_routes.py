from fastapi.testclient import TestClient

from app.main import app, split_ingest_text


client = TestClient(app)


def test_public_service_pages_render():
    for path in ("/", "/agents", "/docs", "/examples", "/security", "/status", "/changelog"):
        response = client.get(path)
        assert response.status_code == 200
    docs = client.get("/docs")
    assert "Plug agents into memory" in docs.text
    assert "/api/workspaces/{slug}/usage" in docs.text
    assert "/api/workspaces/{slug}/ingest" in docs.text
    assert "/api/workspaces/{slug}/export/recent" in docs.text
    pricing = client.get("/pricing", follow_redirects=False)
    assert pricing.status_code == 302
    assert pricing.headers["location"] == "/docs"


def test_public_service_metadata_routes():
    service_status = client.get("/api/service/status")
    assert service_status.status_code == 200
    assert service_status.json()["service"] == "memorylayer"
    assert service_status.json()["features"] >= 20

    robots = client.get("/robots.txt")
    assert robots.status_code == 200
    assert "Sitemap:" in robots.text

    sitemap = client.get("/sitemap.xml")
    assert sitemap.status_code == 200
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
