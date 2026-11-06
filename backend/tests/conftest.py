"""End-to-end / unit test harness for the Niche Podcast Clipper backend.

The suite drives the *real* FastAPI application in-process through Starlette's
``TestClient`` (real routing, real dependency wiring, real request/response
cycle) against an isolated SQLite database and a temporary media directory,
with Redis, Celery and the local Hugging Face models stubbed out. That keeps
every test hermetic and fast while still exercising the whole HTTP surface.

Run the suite from the ``backend/`` directory::

    pytest
"""

from __future__ import annotations

import os
import sys
import tempfile
import types
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Configure the environment BEFORE importing any application module.
#    ``core.config.settings`` (and therefore ``db.session.engine``) are built
#    at import time, so these values must be in place first. Environment
#    variables take precedence over any developer ``.env`` file.
# ---------------------------------------------------------------------------
_TMP = Path(tempfile.mkdtemp(prefix="npc-tests-"))

os.environ.update(
    {
        "ENVIRONMENT": "development",
        "DEBUG": "false",
        "ENABLE_DOCS": "true",
        "AUTO_MIGRATE_DB": "false",
        "DATABASE_URL": f"sqlite+pysqlite:///{_TMP / 'test.db'}",
        "STORAGE_DIR": str(_TMP / "media_storage"),
        "HF_HOME": str(_TMP / "hf"),
        "SECRET_KEY": "test-secret-key-not-for-production",
        "REFRESH_SECRET_KEY": "test-refresh-secret-key-not-for-production",
        "ALGORITHM": "HS256",
        "ACCESS_TOKEN_EXPIRE_MINUTES": "30",
        "REFRESH_TOKEN_EXPIRE_MINUTES": "10080",
        # Real Redis/Celery endpoints are pointed at closed local ports so any
        # code path the harness does not stub fails *open* (instantly refused)
        # instead of hanging; the harness swaps in an in-memory fake below so
        # the cache/rate-limit paths are still exercised.
        "REDIS_URL": "redis://127.0.0.1:6390/0",
        "CELERY_BROKER_URL": "redis://127.0.0.1:6391/0",
        "CELERY_RESULT_BACKEND": "redis://127.0.0.1:6392/0",
        # Effectively disable the limiters so a stray call can never throttle.
        "RATE_LIMIT_REQUESTS": "1000000",
        "RATE_LIMIT_WINDOW_SECONDS": "60",
        "AUTH_RATE_LIMIT_REQUESTS": "1000000",
        "AUTH_RATE_LIMIT_WINDOW_SECONDS": "60",
        "AI_DEVICE": "cpu",
        "AI_NUM_THREADS": "1",
    }
)


# ---------------------------------------------------------------------------
# 2. Replace the Celery task modules with in-process stubs. The routers import
#    these lazily (``from tasks.ai_tasks import ...`` inside the handler), so
#    shadowing the modules in ``sys.modules`` intercepts every dispatch without
#    touching the real broker or loading torch / transformers.
# ---------------------------------------------------------------------------
DISPATCH: list = []


class _FakeAsyncResult:
    """Minimal stand-in for ``celery.result.AsyncResult`` (``.id`` is used)."""

    def __init__(self, task_id=None) -> None:
        self.id = task_id


class _FakeTask:
    """Records dispatches instead of talking to a broker."""

    def __init__(self, name: str) -> None:
        self.name = name

    def delay(self, *args, **kwargs):
        DISPATCH.append((self.name, "delay", args, kwargs))
        return _FakeAsyncResult(None)

    def apply_async(self, *args, **kwargs):
        DISPATCH.append((self.name, "apply_async", args, kwargs))
        return _FakeAsyncResult(None)


def _install_fake_task_modules() -> None:
    package = types.ModuleType("tasks")
    package.__path__ = []  # mark as a package so submodule imports resolve

    ai_tasks = types.ModuleType("tasks.ai_tasks")
    ai_tasks.transcribe_episode_task = _FakeTask("tasks.ai.transcribe_episode")
    ai_tasks.extract_highlights_task = _FakeTask("tasks.ai.extract_highlights")
    ai_tasks.prewarm_models_task = _FakeTask("tasks.ai.prewarm_models")

    video_tasks = types.ModuleType("tasks.video_tasks")
    video_tasks.render_clip_task = _FakeTask("tasks.video.render_clip")

    package.ai_tasks = ai_tasks
    package.video_tasks = video_tasks
    sys.modules["tasks"] = package
    sys.modules["tasks.ai_tasks"] = ai_tasks
    sys.modules["tasks.video_tasks"] = video_tasks


_install_fake_task_modules()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from db.session import Base, SessionLocal, engine  # noqa: E402
from main import app as fastapi_app  # noqa: E402
from models import (  # noqa: E402
    Clip,
    ClipShare,
    Episode,
    RenderJob,
    Transcript,
    User,
)
from models.enums import (  # noqa: E402
    ClipStatus,
    EpisodeStatus,
    JobStatus,
    JobType,
)
from services import caption_styles, storage  # noqa: E402

from fake_redis import FakeRedis  # noqa: E402  (local test helper)

# ---------------------------------------------------------------------------
# 3. Swap the Redis client for an in-memory fake so the cache, the fixed-window
#    rate limiter and the refresh-token blacklist are all exercised end to end.
#    ``core.redis_client.get_redis`` is a plain function, so monkeypatching the
#    module attribute is enough: every caller resolves it at call time.
# ---------------------------------------------------------------------------
import core.redis_client as redis_client  # noqa: E402

_FAKE_REDIS = FakeRedis()  # one process-wide store, so cache state persists
redis_client.get_redis = lambda: _FAKE_REDIS  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# 4. Neutralise Celery *control* commands. ``/jobs/{id}/revoke`` broadcasts a
#    revoke to the broker and ``/health/worker`` pings it; against the closed
#    broker URL these would retry with backoff and stall the suite. Patch the
#    ``Control`` methods on the class so interception holds even if
#    ``app.control`` returns a fresh object on each access.
# ---------------------------------------------------------------------------
from celery.app.control import Control as _Control  # noqa: E402

_Control.ping = lambda self, *a, **k: []  # type: ignore[assignment]
_Control.revoke = lambda self, *a, **k: None  # type: ignore[assignment]
_Control.inspect = lambda self, *a, **k: None  # type: ignore[assignment]

API = "/api/v1"

# Build the schema once; every test starts from an empty database.
Base.metadata.create_all(bind=engine)
storage.ensure_storage()



def _reset_database() -> None:
    """Delete every row so tests never observe each other's state."""
    with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            connection.execute(table.delete())


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_state():
    """Give every test an empty database, cache and dispatch log."""
    DISPATCH.clear()
    _reset_database()
    _FAKE_REDIS._data.clear()
    _FAKE_REDIS._expiry.clear()
    yield
    DISPATCH.clear()


@pytest.fixture
def api() -> str:
    """The versioned API prefix (e.g. ``/api/v1``)."""
    return API


@pytest.fixture
def dispatch() -> list:
    """The Celery dispatch log filled by the stubbed task modules."""
    return DISPATCH


@pytest.fixture
def client() -> TestClient:
    """In-process HTTP client bound to the real application.

    The client is intentionally *not* used as a context manager: that would run
    the ``lifespan`` startup (PostgreSQL probe, Alembic bootstrap and the model
    warm-up thread), none of which the request handlers depend on. The schema is
    created by the harness instead.
    """
    return TestClient(fastapi_app)


def sign_up(client: TestClient, email: str, password: str = "supersecret1", **extra) -> dict:
    """Register an account through the public endpoint and return its payload."""
    response = client.post(
        f"{API}/auth/register",
        json={"email": email, "password": password, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth_headers(client: TestClient, email: str, password: str = "supersecret1") -> dict:
    """Log in via the OAuth2 form endpoint and return a bearer header dict."""
    response = client.post(
        f"{API}/auth/token",
        data={"username": email, "password": password},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


@pytest.fixture
def user_credentials() -> dict:
    return {"email": "creator@example.com", "password": "supersecret1"}


@pytest.fixture
def user(client: TestClient, user_credentials) -> dict:
    """A registered, active account (returns the ``UserRead`` payload)."""
    return sign_up(
        client,
        user_credentials["email"],
        user_credentials["password"],
        full_name="Creator",
    )


@pytest.fixture
def auth(client: TestClient, user, user_credentials) -> dict:
    """Bearer headers for the ``user`` fixture."""
    return auth_headers(client, user_credentials["email"], user_credentials["password"])


@pytest.fixture
def owner_id(user) -> int:
    return user["id"]


@pytest.fixture
def make_user(client: TestClient):
    """Factory: register additional accounts and return their credentials."""

    def _make(email: str, password: str = "supersecret1", **extra):
        sign_up(client, email, password, **extra)
        return {"email": email, "password": password, "headers": auth_headers(client, email, password)}

    return _make


@pytest.fixture
def make_superuser(client: TestClient):
    """Factory: create a superuser directly and return its bearer headers."""

    def _make(email: str = "admin@example.com"):
        from core.security import hash_password

        with SessionLocal() as db:
            record = User(
                email=email,
                full_name="Admin",
                hashed_password=hash_password("supersecret1"),
                is_active=True,
                is_superuser=True,
            )
            db.add(record)
            db.commit()
        return {"email": email, "password": "supersecret1", "headers": auth_headers(client, email)}

    return _make


@pytest.fixture
def make_episode():
    """Factory: persist an episode row directly and return its id."""

    def _make(owner_id: int, **overrides) -> int:
        payload = {
            "owner_id": owner_id,
            "title": "Test episode",
            "description": "A description",
            "stored_filename": "stored.mp3",
            "media_path": "episodes/0/0/stored.mp3",
            "media_type": "audio",
            "mime_type": "audio/mpeg",
            "has_video_stream": False,
            "status": EpisodeStatus.TRANSCRIBED.value,
            "file_size_bytes": 2048,
            "duration_seconds": 120.0,
        }
        payload.update(overrides)
        with SessionLocal() as db:
            episode = Episode(**payload)
            db.add(episode)
            db.commit()
            db.refresh(episode)
            return episode.id

    return _make


@pytest.fixture
def make_clip():
    """Factory: persist a clip row (with sane caption/framing) and return its id."""

    def _make(episode_id: int, owner_id: int, **overrides) -> int:
        transcript_text = overrides.pop("transcript_text", "welcome to the show folks")
        start = overrides.pop("start_time", 0.0)
        end = overrides.pop("end_time", 30.0)
        payload = {
            "episode_id": episode_id,
            "owner_id": owner_id,
            "title": "A clip",
            "hook": "the hook",
            "summary": "a summary",
            "start_time": start,
            "end_time": end,
            "duration_seconds": round(end - start, 3),
            "transcript_text": transcript_text,
            "words": [
                {"word": token, "start": index * 0.4, "end": index * 0.4 + 0.35}
                for index, token in enumerate(transcript_text.split())
            ],
            "virality_score": 0.8,
            "caption_style": caption_styles.caption_style_to_dict(None),
            "framing": caption_styles.framing_to_dict(None),
            "status": ClipStatus.READY.value,
        }
        payload.update(overrides)
        with SessionLocal() as db:
            clip = Clip(**payload)
            db.add(clip)
            db.commit()
            db.refresh(clip)
            return clip.id

    return _make


@pytest.fixture
def make_share():
    """Factory: create a public share link row for a clip."""

    def _make(clip_id: int, owner_id: int, *_, token: str = "sharetoken", **overrides) -> int:
        with SessionLocal() as db:
            share = ClipShare(clip_id=clip_id, owner_id=owner_id, token=token, **overrides)
            db.add(share)
            db.commit()
            db.refresh(share)
            return share.id

    return _make


@pytest.fixture
def make_job():
    """Factory: persist a RenderJob row for ownership/listing tests."""

    def _make(**overrides) -> int:
        payload = {
            "job_type": JobType.RENDER.value,
            "status": JobStatus.PENDING.value,
        }
        payload.update(overrides)
        with SessionLocal() as db:
            job = RenderJob(**payload)
            db.add(job)
            db.commit()
            db.refresh(job)
            return job.id

    return _make


@pytest.fixture
def make_transcript():
    """Factory: attach a transcript (with segments) to an episode."""

    def _make(episode_id: int, **overrides) -> int:
        text = overrides.pop("text", "hello world")
        payload = {
            "episode_id": episode_id,
            "text": text,
            "language": "en",
            "model_name": "openai/whisper-base",
            "duration_seconds": 120.0,
            "word_count": len(text.split()),
        }
        payload.update(overrides)
        with SessionLocal() as db:
            transcript = Transcript(**payload)
            db.add(transcript)
            db.commit()
            db.refresh(transcript)
            return transcript.id

    return _make


