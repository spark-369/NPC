"""Clip caption export/timeline, favourites and public share links."""

API = "/api/v1"


def _captions_clip(make_episode, make_clip, owner_id, **overrides):
    return make_clip(
        make_episode(owner_id),
        owner_id,
        transcript_text="welcome to the show folks",
        start_time=0.0,
        end_time=2.0,
        words=[
            {"word": token, "start": index * 0.4, "end": index * 0.4 + 0.38}
            for index, token in enumerate("welcome to the show folks".split())
        ],
        **overrides,
    )


def test_captions_file_srt(client, auth, owner_id, make_episode, make_clip):
    clip_id = _captions_clip(make_episode, make_clip, owner_id)
    response = client.get(f"{API}/clips/{clip_id}/captions-file", headers=auth, params={"fmt": "srt"})
    assert response.status_code == 200
    assert response.text.splitlines()[1].count("-->") == 1
    assert "," in response.text.splitlines()[1]  # SRT uses a comma
    assert "attachment" in response.headers["content-disposition"]


def test_captions_file_vtt(client, auth, owner_id, make_episode, make_clip):
    clip_id = _captions_clip(make_episode, make_clip, owner_id)
    response = client.get(f"{API}/clips/{clip_id}/captions-file", headers=auth, params={"fmt": "vtt"})
    assert response.status_code == 200
    assert response.text.startswith("WEBVTT")


def test_captions_file_rejects_unknown_format(client, auth, owner_id, make_episode, make_clip):
    clip_id = _captions_clip(make_episode, make_clip, owner_id)
    response = client.get(f"{API}/clips/{clip_id}/captions-file", headers=auth, params={"fmt": "docx"})
    assert response.status_code == 422


def test_caption_timeline_returns_clip_relative_groups(client, auth, owner_id, make_episode, make_clip):
    clip_id = _captions_clip(make_episode, make_clip, owner_id)
    response = client.get(f"{API}/clips/{clip_id}/caption-timeline", headers=auth)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["clip_id"] == clip_id
    assert body["words_per_line"] == 3
    assert len(body["groups"]) >= 1
    first_group = body["groups"][0]
    assert first_group["words"][0]["text"] == "welcome"
    assert first_group["start"] >= 0.0


def test_caption_timeline_accepts_draft_overrides(client, auth, owner_id, make_episode, make_clip):
    clip_id = _captions_clip(make_episode, make_clip, owner_id)
    response = client.get(
        f"{API}/clips/{clip_id}/caption-timeline",
        headers=auth,
        params={"transcript": "totally different words now", "start_time": 0.0, "end_time": 3.0},
    )
    assert response.status_code == 200
    texts = " ".join(w["text"] for g in response.json()["groups"] for w in g["words"])
    assert "totally" in texts


def test_toggle_favorite(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    first = client.post(f"{API}/clips/{clip_id}/favorite", headers=auth)
    assert first.status_code == 200
    assert first.json()["is_favorite"] is True
    second = client.post(f"{API}/clips/{clip_id}/favorite", headers=auth)
    assert second.json()["is_favorite"] is False


def test_create_share_link_with_expiry(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    response = client.post(
        f"{API}/clips/{clip_id}/shares", headers=auth, json={"expires_in_days": 7}
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["url"].startswith(f"{API}/public/clips/")
    assert body["token"]
    assert body["is_active"] is True
    assert body["expires_at"] is not None


def test_create_share_link_never_expires_by_default(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    body = client.post(f"{API}/clips/{clip_id}/shares", headers=auth, json={}).json()
    assert body["expires_at"] is None
    assert body["is_active"] is True


def test_list_share_links(client, auth, owner_id, make_episode, make_clip, make_share):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    make_share(clip_id, owner_id, token="one")
    make_share(clip_id, owner_id, token="two")
    response = client.get(f"{API}/clips/{clip_id}/shares", headers=auth)
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_revoke_share_link(client, auth, owner_id, make_episode, make_clip, make_share):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    share_id = make_share(clip_id, owner_id, token="revokeme")
    assert client.delete(f"{API}/clips/{clip_id}/shares/{share_id}", headers=auth).status_code == 204
    active = [s for s in client.get(f"{API}/clips/{clip_id}/shares", headers=auth).json() if s["is_active"]]
    assert active == []


def test_clip_jobs_history(client, auth, owner_id, make_episode, make_clip, make_job):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    make_job(clip_id=clip_id, status="success")
    response = client.get(f"{API}/clips/{clip_id}/jobs", headers=auth)
    assert response.status_code == 200
    assert len(response.json()) == 1


def test_clip_download_conflicts_when_not_rendered(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)  # no output_path
    access_token = auth["Authorization"].split(" ", 1)[1]
    response = client.get(f"{API}/clips/{clip_id}/download", params={"token": access_token})
    assert response.status_code == 409


def test_clip_download_streams_the_render(client, auth, owner_id, make_episode, make_clip):
    from services import storage

    clip_id = make_clip(
        make_episode(owner_id), owner_id, output_path="clips/1/1/render.mp4"
    )
    target = storage.absolute_media_path("clips/1/1/render.mp4")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"mp4-bytes")
    access_token = auth["Authorization"].split(" ", 1)[1]
    try:
        response = client.get(f"{API}/clips/{clip_id}/download", params={"token": access_token})
        assert response.status_code == 200
        assert response.headers["content-type"] == "video/mp4"
        assert response.content == b"mp4-bytes"
    finally:
        target.unlink(missing_ok=True)


def test_clip_download_requires_valid_token(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    assert client.get(f"{API}/clips/{clip_id}/download").status_code == 401
    assert (
        client.get(f"{API}/clips/{clip_id}/download", params={"token": "bad"}).status_code == 401
    )


def test_clip_thumbnail_404_without_a_thumbnail(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)  # no thumbnail_path
    access_token = auth["Authorization"].split(" ", 1)[1]
    response = client.get(f"{API}/clips/{clip_id}/thumbnail", params={"token": access_token})
    assert response.status_code == 404


def test_clip_thumbnail_streams_jpeg(client, auth, owner_id, make_episode, make_clip):
    from services import storage

    clip_id = make_clip(
        make_episode(owner_id), owner_id, thumbnail_path="clips/2/2/thumb.jpg"
    )
    target = storage.absolute_media_path("clips/2/2/thumb.jpg")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"jpeg-bytes")
    access_token = auth["Authorization"].split(" ", 1)[1]
    try:
        response = client.get(f"{API}/clips/{clip_id}/thumbnail", params={"token": access_token})
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == b"jpeg-bytes"
    finally:
        target.unlink(missing_ok=True)
