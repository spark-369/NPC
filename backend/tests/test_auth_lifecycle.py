"""Authentication lifecycle: refresh rotation, logout and session introspection."""

API = "/api/v1"


def _login(client, creds):
    return client.post(
        f"{API}/auth/token",
        data={"username": creds["email"], "password": creds["password"]},
    ).json()


def test_refresh_rotates_and_blacklists(client, user, user_credentials):
    login = _login(client, user_credentials)
    refresh_token = login["refresh_token"]

    first = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200, first.text
    assert "access_token" in first.json()

    # The same refresh token must not work twice (rotation blacklists it).
    second = client.post(f"{API}/auth/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401


def test_refresh_rejects_access_token(client, user, auth):
    access_token = auth["Authorization"].split(" ", 1)[1]
    response = client.post(f"{API}/auth/refresh", json={"refresh_token": access_token})
    assert response.status_code == 401


def test_logout_blacklists_refresh_token(client, user, user_credentials):
    login = _login(client, user_credentials)
    logout = client.post(f"{API}/auth/logout", json={"refresh_token": login["refresh_token"]})
    assert logout.status_code == 200
    assert logout.json()["message"] == "Signed out"
    # The revoked token can no longer be exchanged.
    assert (
        client.post(
            f"{API}/auth/refresh", json={"refresh_token": login["refresh_token"]}
        ).status_code
        == 401
    )


def test_session_info_reports_the_cached_session(client, user, auth):
    # Two requests: the first populates the identity cache, the second reads it.
    client.get(f"{API}/auth/me", headers=auth)
    response = client.get(f"{API}/auth/session", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == user["id"]
    assert body["cached"] is True
    assert body["access_token_ttl_seconds"] > 0