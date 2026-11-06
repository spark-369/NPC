"""Root and health endpoints (no authentication required)."""


def test_root_banner(client):
    response = client.get("/")
    assert response.status_code == 200
    body = response.json()
    assert body["app"] == "Niche Podcast Clipper"
    assert body["api"] == "/api/v1"
    assert body["ai"]["on_premise"] is True
    assert body["docs"] == "/docs"


def test_ping_is_dependency_free(client):
    response = client.get("/ping")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_openapi_schema_exposes_every_router(client):
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]
    # A representative path from every router is registered.
    for path in (
        "/api/v1/health",
        "/api/v1/auth/token",
        "/api/v1/episodes",
        "/api/v1/clips",
        "/api/v1/jobs",
        "/api/v1/search",
        "/api/v1/stats/overview",
        "/api/v1/public/clips/{token}",
        "/api/v1/admin/users",
    ):
        assert path in paths, f"missing route {path}"


def test_health_reports_ok_with_redis_and_database(client):
    """Both dependencies resolve (fake Redis + SQLite), so health is ok."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["database"] is True
    assert body["redis"] is True
    assert body["status"] == "ok"
    assert body["app_name"] == "Niche Podcast Clipper"


def test_health_models_describes_local_checkpoints(client):
    body = client.get("/api/v1/health/models").json()
    assert body["asr_model"] == "openai/whisper-base"
    assert body["highlight_model"] == "google/flan-t5-base"
    assert body["on_premise"] is True
    assert body["device"] == "cpu"


def test_health_worker_fails_gracefully_without_broker(client):
    """No Celery worker is running; the probe must answer, not raise.

    The harness stubs ``Control.ping`` (it would otherwise block against the
    closed broker), so the endpoint always reports zero workers.
    """
    response = client.get("/api/v1/health/worker")
    assert response.status_code == 200
    body = response.json()
    assert body["healthy"] is False
    assert body["workers_online"] == 0


def test_ready_probe_reports_ready(client):
    response = client.get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == {"database": True, "redis": True}
