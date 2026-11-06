"""Episode endpoints: upload, list, detail, update, delete, transcribe, media."""

import io

API = "/api/v1"


def _upload(client, headers, filename="episode.mp3", data=b"fake-audio-bytes", **fields):
    files = {"file": (filename, io.BytesIO(data), "audio/mpeg")}
    return client.post(f"{API}/episodes/upload", headers=headers, files=files, data=fields)


def test_upload_persists_the_file_and_returns_metadata(client, auth):
    response = _upload(client, auth, title="My Episode")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["message"] == "Episode uploaded successfully"
    episode = body["episode"]
    assert episode["title"] == "My Episode"
    assert episode["status"] == "uploaded"
    assert episode["file_size_bytes"] == len(b"fake-audio-bytes")
    assert episode["has_transcript"] is False
    assert episode["clip_count"] == 0


def test_upload_derives_title_from_filename_when_omitted(client, auth):
    response = _upload(client, auth, filename="my-great-show.mp3")
    assert response.status_code == 201
    assert response.json()["episode"]["title"] == "my-great-show"


def test_upload_rejects_unsupported_extension(client, auth):
    response = _upload(client, auth, filename="notes.pdf", data=b"%PDF")
    assert response.status_code == 415


def test_upload_requires_authentication(client):
    response = _upload(client, headers={}, filename="episode.mp3")
    assert response.status_code == 401


def test_upload_with_auto_transcribe_queues_a_task(client, auth, dispatch):
    response = _upload(client, auth, auto_transcribe="true")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["episode"]["status"] == "queued"
    assert "transcription queued" in body["message"]
    # BackgroundTasks run once the response is produced; TestClient waits for them.
    assert any(name == "tasks.ai.transcribe_episode" for name, *_ in dispatch)


def test_list_episodes_scoped_to_owner(client, auth, owner_id, make_episode, make_user):
    make_episode(owner_id, title="Mine")
    other = make_user("other@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    make_episode(other_id, title="Theirs")

    response = client.get(f"{API}/episodes", headers=auth)
    assert response.status_code == 200
    titles = [episode["title"] for episode in response.json()]
    assert titles == ["Mine"]


def test_list_episodes_filters_by_status(client, auth, owner_id, make_episode):
    make_episode(owner_id, title="Uploaded", status="uploaded")
    make_episode(owner_id, title="Transcribed", status="transcribed")
    response = client.get(f"{API}/episodes", headers=auth, params={"status": "uploaded"})
    assert response.status_code == 200
    assert [e["title"] for e in response.json()] == ["Uploaded"]


def test_read_episode_detail(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id, title="Detail episode")
    make_clip(episode_id, owner_id)
    response = client.get(f"{API}/episodes/{episode_id}", headers=auth)
    assert response.status_code == 200
    assert response.json()["clip_count"] == 1


def test_read_episode_404_for_other_users(client, auth, make_episode, make_user):
    other = make_user("stranger@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    episode_id = make_episode(other_id)
    assert client.get(f"{API}/episodes/{episode_id}", headers=auth).status_code == 404


def test_update_episode(client, auth, owner_id, make_episode):
    episode_id = make_episode(owner_id, title="Old")
    response = client.patch(
        f"{API}/episodes/{episode_id}",
        headers=auth,
        json={"title": "New", "description": "desc"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "New"
    assert body["description"] == "desc"


def test_delete_episode_removes_row_and_clips(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id)
    assert client.delete(f"{API}/episodes/{episode_id}", headers=auth).status_code == 204
    assert client.get(f"{API}/episodes/{episode_id}", headers=auth).status_code == 404
    assert client.get(f"{API}/clips", headers=auth).json() == []
