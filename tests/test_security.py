from fastapi.testclient import TestClient

from app.main import app
from app.security import digest_token, mint_prefixed_token


def test_digest_token_is_stable():
    assert digest_token("abc") == digest_token("abc")


def test_mint_prefixed_token_shapes_output():
    token, prefix, token_hash = mint_prefixed_token("engram")

    assert token.startswith("engram_")
    assert prefix.startswith("engram_")
    assert len(token_hash) == 64
    assert digest_token(token) == token_hash


def test_security_headers_are_present_on_public_pages():
    client = TestClient(app)
    response = client.get("/security")

    assert response.status_code == 200
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert "object-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["referrer-policy"] == "strict-origin-when-cross-origin"
    client.close()


def test_unknown_hosts_are_rejected():
    client = TestClient(app)
    response = client.get("/", headers={"host": "evil.example"})

    assert response.status_code == 400
    assert response.text == "Invalid host"
    client.close()


def test_cross_origin_browser_post_is_blocked():
    client = TestClient(app)
    response = client.post(
        "/app/workspaces",
        data={"name": "cross site"},
        headers={"origin": "https://evil.example"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert "This boundary held." in response.text
    client.close()


def test_suspicious_python_server_probe_paths_are_blocked():
    client = TestClient(app)

    assert client.get("/%2e%2e/%2e%2e/etc/passwd").status_code == 400
    assert client.get("/.env").status_code == 400
    assert client.get("/wp-login.php").status_code == 404
    client.close()


def test_unsafe_http_methods_are_blocked_before_routing():
    client = TestClient(app)
    response = client.request("TRACE", "/")

    assert response.status_code == 405
    assert "Wrong motion for this route." in response.text
    client.close()
