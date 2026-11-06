"""Unit tests for security helpers: password hashing and JWT tokens."""

import time
from datetime import timedelta

import pytest
from jose import JWTError

from core.security import (
    ACCESS_TOKEN_TYPE,
    REFRESH_TOKEN_TYPE,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_password_hash_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed) is True
    assert verify_password("wrong", hashed) is False


def test_verify_password_survives_malformed_hash():
    # passlib raises ValueError on a non-bcrypt hash; the helper must swallow it.
    assert verify_password("anything", "not-a-valid-hash") is False


def test_access_token_roundtrip():
    token = create_access_token("42", extra_claims={"email": "a@b.com"})
    payload = decode_token(token, token_type=ACCESS_TOKEN_TYPE)
    assert payload["sub"] == "42"
    assert payload["type"] == "access"
    assert payload["email"] == "a@b.com"
    assert payload["exp"] > payload["iat"]


def test_refresh_token_roundtrip():
    token = create_refresh_token("7")
    payload = decode_token(token, token_type=REFRESH_TOKEN_TYPE)
    assert payload["sub"] == "7"
    assert payload["type"] == "refresh"


def test_decode_rejects_wrong_token_type():
    access = create_access_token("1")
    with pytest.raises(JWTError):
        decode_token(access, token_type=REFRESH_TOKEN_TYPE)


def test_decode_rejects_tampered_token():
    token = create_access_token("1")
    with pytest.raises(JWTError):
        decode_token(token + "tampered", token_type=ACCESS_TOKEN_TYPE)


def test_decode_rejects_expired_token():
    token = create_access_token("1", expires_delta=timedelta(seconds=-1))
    time.sleep(0.01)
    with pytest.raises(JWTError):
        decode_token(token, token_type=ACCESS_TOKEN_TYPE)


def test_access_and_refresh_use_different_signing_keys():
    """A refresh token signed with REFRESH_SECRET_KEY must not verify as access."""
    refresh = create_refresh_token("5")
    with pytest.raises(JWTError):
        decode_token(refresh, token_type=ACCESS_TOKEN_TYPE)
