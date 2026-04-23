from fastapi.testclient import TestClient

from app.main import app


client = TestClient(app)


def test_public_service_pages_render():
    for path in ("/", "/agents", "/pricing", "/docs"):
        response = client.get(path)
        assert response.status_code == 200


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
