"""Superuser administration routes."""

API = "/api/v1"


def _register_and_id(client, email: str, password: str = "supersecret1") -> int:
    """Register a user through the public flow and return its id."""
    client.post(f"{API}/auth/register", json={"email": email, "password": password})
    token = client.post(
        f"{API}/auth/token", data={"username": email, "password": password}
    ).json()["access_token"]
    return client.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["id"]


def test_admin_requires_superuser(client, auth):
    assert client.get(f"{API}/admin/users", headers=auth).status_code == 403


def test_admin_requires_auth(client):
    assert client.get(f"{API}/admin/users").status_code == 401


def test_list_users_includes_content_counters(client, make_superuser, make_episode, make_clip):
    admin = make_superuser()
    member_id = _register_and_id(client, "member@example.com")
    episode_id = make_episode(member_id)
    make_clip(episode_id, member_id)

    response = client.get(f"{API}/admin/users", headers=admin["headers"])
    assert response.status_code == 200
    by_email = {user["email"]: user for user in response.json()}
    assert by_email["member@example.com"]["episode_count"] == 1
    assert by_email["member@example.com"]["clip_count"] == 1


def test_admin_can_deactivate_and_promote(client, make_superuser):
    admin = make_superuser("root@example.com")
    member_id = _register_and_id(client, "victim@example.com")

    response = client.patch(
        f"{API}/admin/users/{member_id}",
        headers=admin["headers"],
        json={"is_active": False, "is_superuser": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["is_active"] is False
    assert body["is_superuser"] is True


def test_admin_cannot_lock_itself_out(client, make_superuser):
    admin = make_superuser("self@example.com")
    admin_id = client.get(f"{API}/auth/me", headers=admin["headers"]).json()["id"]
    response = client.patch(
        f"{API}/admin/users/{admin_id}",
        headers=admin["headers"],
        json={"is_active": False},
    )
    assert response.status_code == 400


def test_admin_update_404_for_unknown_user(client, make_superuser):
    admin = make_superuser()
    assert (
        client.patch(
            f"{API}/admin/users/99999", headers=admin["headers"], json={"is_active": False}
        ).status_code
        == 404
    )


def test_admin_search_filter(client, make_superuser):
    admin = make_superuser()
    _register_and_id(client, "findme@example.com")
    response = client.get(
        f"{API}/admin/users", headers=admin["headers"], params={"q": "findme"}
    )
    assert response.status_code == 200
    assert [u["email"] for u in response.json()] == ["findme@example.com"]

