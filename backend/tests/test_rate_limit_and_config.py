"""Rate limiting, config validation and cache helpers."""

import pytest

from core.config import Settings
from core.redis_client import cache_delete, cache_get_json, cache_set_json, check_rate_limit

API = "/api/v1"


def test_settings_csv_fields_are_split():
    settings = Settings(
        FRONTEND_ORIGINS="http://a.com, http://b.com",
        ALLOWED_MEDIA_EXTENSIONS=".mp3,.wav",
    )
    assert settings.FRONTEND_ORIGINS == ["http://a.com", "http://b.com"]
    assert settings.ALLOWED_MEDIA_EXTENSIONS == [".mp3", ".wav"]


def test_settings_reject_template_secrets_in_production():
    with pytest.raises(ValueError):
        Settings(ENVIRONMENT="production", SECRET_KEY="change-me-super-secret-jwt-key")


def test_settings_accept_strong_secrets_in_production():
    settings = Settings(
        ENVIRONMENT="production",
        SECRET_KEY="a-very-long-random-production-secret",
        REFRESH_SECRET_KEY="another-very-long-random-production-secret",
    )
    assert settings.is_production is True


def test_is_production_flag():
    assert Settings(ENVIRONMENT="production").is_production is True
    assert Settings(ENVIRONMENT="development").is_production is False


def test_cache_set_and_get_roundtrip():
    cache_set_json("unit:key", {"a": 1, "b": [1, 2]})
    assert cache_get_json("unit:key") == {"a": 1, "b": [1, 2]}
    cache_delete("unit:key")
    assert cache_get_json("unit:key") is None


def test_cache_get_missing_key_returns_none():
    assert cache_get_json("unit:missing") is None


def test_check_rate_limit_allows_then_blocks():
    allowed, remaining = check_rate_limit("unit:limit", limit=3, window=60)
    assert allowed is True
    assert remaining == 2
    check_rate_limit("unit:limit", limit=3, window=60)
    allowed, remaining = check_rate_limit("unit:limit", limit=3, window=60)
    assert allowed is True
    assert remaining == 0
    allowed, _ = check_rate_limit("unit:limit", limit=3, window=60)
    assert allowed is False


def test_auth_rate_limit_returns_429(client, monkeypatch):
    from core.config import settings

    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_REQUESTS", 2)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_WINDOW_SECONDS", 60)

    payload = {"email": "ratelimited@example.com", "password": "supersecret1"}
    assert client.post(f"{API}/auth/register", json=payload).status_code == 201
    # The 2nd and 3rd attempts exceed the (lowered) budget.
    codes = [client.post(f"{API}/auth/login", json=payload).status_code for _ in range(3)]
    assert 429 in codes
