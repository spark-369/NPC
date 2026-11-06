"""Episode transcription, transcripts, media streaming and stats."""

API = "/api/v1"


def test_transcribe_queues_a_task_and_mirrors_status(client, auth, owner_id, make_episode, dispatch):
    episode_id = make_episode(owner_id, status="uploaded")
    response = client.post(f"{API}/episodes/{episode_id}/transcribe", headers=auth, json={})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued"
    assert body["cached"] is False
    assert body["job_id"] is not None
    assert any(name == "tasks.ai.transcribe_episode" for name, *_ in dispatch)
    # The episode's status is flipped to queued immediately.
    assert client.get(f"{API}/episodes/{episode_id}", headers=auth).json()["status"] == "queued"


def test_transcribe_returns_cached_when_transcript_exists(client, auth, owner_id, make_episode, make_transcript):
    episode_id = make_episode(owner_id, status="transcribed")
    make_transcript(episode_id)
    response = client.post(f"{API}/episodes/{episode_id}/transcribe", headers=auth, json={})
    assert response.status_code == 200
    body = response.json()
    assert body["cached"] is True
    assert body["job_id"] is None


def test_transcribe_force_requeues(client, auth, owner_id, make_episode, make_transcript, dispatch):
    episode_id = make_episode(owner_id, status="transcribed")
    make_transcript(episode_id)
    response = client.post(
        f"{API}/episodes/{episode_id}/transcribe", headers=auth, json={"force": True}
    )
    assert response.status_code == 200
    assert response.json()["cached"] is False
    assert any(name == "tasks.ai.transcribe_episode" for name, *_ in dispatch)


def test_read_transcript_404_before_transcription(client, auth, owner_id, make_episode):
    episode_id = make_episode(owner_id)
    response = client.get(f"{API}/episodes/{episode_id}/transcript", headers=auth)
    assert response.status_code == 404


def test_read_transcript_returns_segments(client, auth, owner_id, make_episode, make_transcript):
    episode_id = make_episode(owner_id, status="transcribed")
    make_transcript(episode_id, text="hello beautiful world")
    response = client.get(f"{API}/episodes/{episode_id}/transcript", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "hello beautiful world"
    assert body["language"] == "en"
    assert body["word_count"] == 3


def test_media_stream_requires_a_valid_token(client, auth, owner_id, make_episode):
    episode_id = make_episode(owner_id)
    # No token at all.
    assert client.get(f"{API}/episodes/{episode_id}/media").status_code == 401
    # Bad token.
    assert (
        client.get(f"{API}/episodes/{episode_id}/media", params={"token": "nope"}).status_code
        == 401
    )


def test_media_stream_404_when_file_missing_on_disk(client, auth, owner_id, make_episode):
    access_token = auth["Authorization"].split(" ", 1)[1]
    episode_id = make_episode(owner_id)  # media_path points at a non-existent file
    response = client.get(
        f"{API}/episodes/{episode_id}/media", params={"token": access_token}
    )
    assert response.status_code == 404


def test_episode_stats_aggregates_clips(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, virality_score=0.9)
    make_clip(episode_id, owner_id, virality_score=0.4)
    response = client.get(f"{API}/episodes/{episode_id}/stats", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["clip_count"] == 2
    assert body["best_virality_score"] == 0.9
    assert body["rendered_clip_count"] == 0
