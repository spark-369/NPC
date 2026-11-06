"""Public (unauthenticated) share-link endpoints."""

from datetime import datetime, timedelta, timezone

API = "/api/v1"


def _public_ready_clip(make_episode, make_clip, owner_id, **overrides):
    return make_clip(
        make_episode(owner_id),
        owner_id,
        title="Shared clip",
        thumbnail_path="clips/0/0/thumb.jpg",
        output_path="clips/0/0/render.mp4",
        keywords=["growth", "focus"],
        **overrides,
    )


def test_public_metadata_increments_view_count(client, owner_id, make_episode, make_clip, make_share):
    clip_id = _public_ready_clip(make_episode, make_clip, owner_id)
    make_share(clip_id, owner_id, token="tok-abc")

    response = client.get(f"{API}/public/clips/tok-abc")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Shared clip"
    assert body["view_count"] == 1
    assert body["thumbnail_url"].endswith("/public/clips/tok-abc/thumbnail")
    assert body["download_url"].endswith("/public/clips/tok-abc/download")
    # No owner identity is ever exposed.
    assert "owner_id" not in body

    # A second view increments the counter.
    assert client.get(f"{API}/public/clips/tok-abc").json()["view_count"] == 2


def test_public_metadata_404_for_unknown_token(client):
    assert client.get(f"{API}/public/clips/does-not-exist").status_code == 404


def test_expired_share_answers_410(client, owner_id, make_episode, make_clip, make_share):
    clip_id = _public_ready_clip(make_episode, make_clip, owner_id)
    make_share(
        clip_id,
        owner_id,
        token="expired",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    response = client.get(f"{API}/public/clips/expired")
    assert response.status_code == 410


def test_revoked_share_answers_410(client, owner_id, make_episode, make_clip, make_share):
    clip_id = _public_ready_clip(make_episode, make_clip, owner_id)
    make_share(clip_id, owner_id, token="revoked", revoked_at=datetime.now(timezone.utc))
    assert client.get(f"{API}/public/clips/revoked").status_code == 410


def test_public_download_conflicts_when_not_rendered(client, owner_id, make_episode, make_clip, make_share):
    clip_id = make_clip(make_episode(owner_id), owner_id)  # no output_path
    make_share(clip_id, owner_id, token="norender")
    assert client.get(f"{API}/public/clips/norender/download").status_code == 409


def test_public_download_streams_the_mp4(client, owner_id, make_episode, make_clip, make_share):
    from services import storage

    clip_id = _public_ready_clip(make_episode, make_clip, owner_id)
    make_share(clip_id, owner_id, token="dl")
    # Write the rendered file where the DB row points.
    target = storage.absolute_media_path("clips/0/0/render.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"fake-mp4")
    try:
        response = client.get(f"{API}/public/clips/dl/download")
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == b"fake-mp4"
    finally:
        target.unlink(missing_ok=True)
