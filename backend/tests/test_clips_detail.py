"""Clip detail, editing (render invalidation), delete, render and downloads."""

API = "/api/v1"


def test_read_clip_detail(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id, title="Detail clip")
    response = client.get(f"{API}/clips/{clip_id}", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Detail clip"
    assert body["caption_style"]["preset"] == "tiktok"
    assert body["framing"]["output_height"] == 1920


def test_read_clip_404_for_other_user(client, auth, make_episode, make_clip, make_user):
    other = make_user("stranger@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    clip_id = make_clip(make_episode(other_id), other_id)
    assert client.get(f"{API}/clips/{clip_id}", headers=auth).status_code == 404


def test_update_clip_persists_edits_and_recomputes_duration(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    response = client.patch(
        f"{API}/clips/{clip_id}",
        headers=auth,
        json={"title": "Edited", "start_time": 5.0, "end_time": 20.0, "transcript_text": "new text"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["title"] == "Edited"
    assert body["duration_seconds"] == 15.0
    assert body["transcript_text"] == "new text"


def test_update_clip_rejects_inverted_bounds(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    response = client.patch(
        f"{API}/clips/{clip_id}",
        headers=auth,
        json={"start_time": 30.0, "end_time": 10.0},
    )
    assert response.status_code == 422


def test_update_clip_invalidates_a_stale_render(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(
        make_episode(owner_id),
        owner_id,
        output_path="clips/0/0/rendered.mp4",
        output_size_bytes=12345,
        status="rendered",
    )
    response = client.patch(f"{API}/clips/{clip_id}", headers=auth, json={"hook": "new hook"})
    assert response.status_code == 200
    body = response.json()
    assert body["output_path"] is None
    assert body["output_size_bytes"] == 0
    assert body["status"] == "ready"


def test_update_clip_favorite_flag_via_patch(client, auth, owner_id, make_episode, make_clip):
    """PATCH persists the star flag (the dedicated toggle keeps renders intact)."""
    clip_id = make_clip(make_episode(owner_id), owner_id)
    response = client.patch(f"{API}/clips/{clip_id}", headers=auth, json={"is_favorite": True})
    assert response.status_code == 200
    assert response.json()["is_favorite"] is True


def test_delete_clip(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    assert client.delete(f"{API}/clips/{clip_id}", headers=auth).status_code == 204
    assert client.get(f"{API}/clips/{clip_id}", headers=auth).status_code == 404


def test_render_dispatches_a_job(client, auth, owner_id, make_episode, make_clip, dispatch):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    response = client.post(f"{API}/clips/{clip_id}/render", headers=auth, json={"priority": 3})
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["clip_id"] == clip_id
    assert body["job_id"] is not None
    assert body["status"] == "pending"
    assert any(name == "tasks.video.render_clip" for name, *_ in dispatch)
    # The clip is marked rendering.
    assert client.get(f"{API}/clips/{clip_id}", headers=auth).json()["status"] == "rendering"


def test_render_persists_edited_transcript(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id, transcript_text="original")
    client.post(
        f"{API}/clips/{clip_id}/render", headers=auth, json={"transcript": "edited narration"}
    )
    assert (
        client.get(f"{API}/clips/{clip_id}", headers=auth).json()["transcript_text"]
        == "edited narration"
    )


def test_render_status_404_before_any_job(client, auth, owner_id, make_episode, make_clip):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    assert client.get(f"{API}/clips/{clip_id}/status", headers=auth).status_code == 404


def test_render_status_returns_latest_job(client, auth, owner_id, make_episode, make_clip, make_job):
    clip_id = make_clip(make_episode(owner_id), owner_id)
    make_job(clip_id=clip_id, status="running", progress=42)
    response = client.get(f"{API}/clips/{clip_id}/status", headers=auth)
    assert response.status_code == 200
    assert response.json()["progress"] == 42


def test_render_batch_collapses_duplicates_and_skips_bad_ids(client, auth, owner_id, make_episode, make_clip, dispatch):
    episode_id = make_episode(owner_id)
    good = make_clip(episode_id, owner_id, status="ready")
    rendering = make_clip(episode_id, owner_id, status="rendering")
    response = client.post(
        f"{API}/clips/render-batch",
        headers=auth,
        json={"clip_ids": [good, good, rendering, 99999], "priority": 4},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert [item["clip_id"] for item in body["queued"]] == [good]
    # JSON object keys are strings; both impossible clips are reported.
    assert str(rendering) in body["skipped"]
    assert "99999" in body["skipped"]
    dispatches = [d for d in dispatch if d[0] == "tasks.video.render_clip"]
    assert len(dispatches) == 1  # duplicates collapsed to a single dispatch
