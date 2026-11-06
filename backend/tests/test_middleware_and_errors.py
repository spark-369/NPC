"""Cross-cutting middleware and exception-handler behaviour."""

API = "/api/v1"


def test_responses_carry_hardening_headers(client):
    response = client.get("/ping")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["X-App-Version"] == "1.0.0"
    assert "X-Process-Time-Ms" in response.headers
    assert "X-Request-Id" in response.headers


def test_request_id_is_echoed(client):
    response = client.get("/ping", headers={"X-Request-Id": "trace-123"})
    assert response.headers["X-Request-Id"] == "trace-123"


def test_validation_error_handler_returns_concise_422(client):
    response = client.post(f"{API}/auth/register", json={"email": "x", "password": "y"})
    assert response.status_code == 422
    body = response.json()
    assert body["detail"] == "Request validation failed"
    assert "request_id" in body


def test_cors_preflight_allows_frontend_origin(client):
    response = client.options(
        f"{API}/health",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "GET" in response.headers["access-control-allow-methods"]


def test_cors_simple_response_exposes_content_disposition(client):
    response = client.get("/ping", headers={"Origin": "http://localhost:5173"})
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"
    # Content-Disposition is exposed so the SPA can read download filenames.
    assert "Content-Disposition" in response.headers["access-control-expose-headers"]


def test_openapi_documents_bearer_security(client):
    schema = client.get("/openapi.json").json()
    assert any(
        "OAuth2PasswordBearer" in (scheme.get("type", ""))
        or "oauth2" in (scheme.get("type", ""))
        for scheme in schema["components"]["securitySchemes"].values()
    )
