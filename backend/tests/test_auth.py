"""Authentication: register, OAuth2 token and profile management."""

from conftest import auth_headers

API = "/api/v1"


def test_register_creates_an_active_account(client):
    response = client.post(
        f"{API}/auth/register",
        json={"email": "New.User@Example.com", "password": "supersecret1", "full_name": "New"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["email"] == "new.user@example.com"  # normalised to lower case
    assert body["full_name"] == "New"
    assert body["is_active"] is True
    assert body["is_superuser"] is False
    assert "hashed_password" not in body


def test_register_rejects_duplicate_email(client, user):
    response = client.post(
        f"{API}/auth/register",
        json={"email": user["email"], "password": "supersecret1"},
    )
    assert response.status_code == 409


def test_register_validates_password_length(client):
    response = client.post(
        f"{API}/auth/register",
        json={"email": "short@example.com", "password": "short"},
    )
    assert response.status_code == 422


def test_register_validates_email_format(client):
    response = client.post(
        f"{API}/auth/register",
        json={"email": "not-an-email", "password": "supersecret1"},
    )
    assert response.status_code == 422


def test_login_with_form_returns_token_pair(client, user, user_credentials):
    response = client.post(
        f"{API}/auth/token",
        data={"username": user_credentials["email"], "password": user_credentials["password"]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"] and body["refresh_token"]
    assert body["expires_in"] > 0


def test_json_login_variant(client, user, user_credentials):
    response = client.post(
        f"{API}/auth/login",
        json={"email": user_credentials["email"], "password": user_credentials["password"]},
    )
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_login_rejects_wrong_password(client, user, user_credentials):
    response = client.post(
        f"{API}/auth/token",
        data={"username": user_credentials["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401


def test_inactive_account_cannot_log_in(client, make_superuser):
    creds = make_superuser("inactive@example.com")
    admin = make_superuser("boss@example.com")
    target_id = client.get(f"{API}/auth/me", headers=creds["headers"]).json()["id"]
    client.patch(
        f"{API}/admin/users/{target_id}",
        headers=admin["headers"],
        json={"is_active": False},
    )
    response = client.post(
        f"{API}/auth/token",
        data={"username": creds["email"], "password": creds["password"]},
    )
    assert response.status_code in (401, 403)


def test_me_requires_a_token(client):
    assert client.get(f"{API}/auth/me").status_code == 401


def test_me_rejects_garbage_token(client):
    response = client.get(f"{API}/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_me_returns_the_current_profile(client, user, auth):
    response = client.get(f"{API}/auth/me", headers=auth)
    assert response.status_code == 200
    assert response.json()["email"] == user["email"]


def test_update_profile_changes_name_and_password(client, user, user_credentials):
    headers = auth_headers(client, user_credentials["email"], user_credentials["password"])
    response = client.patch(
        f"{API}/auth/me",
        headers=headers,
        json={"full_name": "Renamed", "password": "brandnewpass1"},
    )
    assert response.status_code == 200
    assert response.json()["full_name"] == "Renamed"
    # The new password works; the old one no longer does.
    assert (
        client.post(
            f"{API}/auth/token",
            data={"username": user_credentials["email"], "password": "brandnewpass1"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"{API}/auth/token",
            data={
                "username": user_credentials["email"],
                "password": user_credentials["password"],
            },
        ).status_code
        == 401
    )


def test_expired_access_token_rejected(client, user):
    from datetime import timedelta

    from core.security import create_access_token

    expired = create_access_token(str(user["id"]), expires_delta=timedelta(seconds=-5))
    response = client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert response.status_code == 401
    assert "expired" in response.json()["detail"].lower()
