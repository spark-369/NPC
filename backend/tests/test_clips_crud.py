"""Clip generation, listing, presets and CSV export."""

API = "/api/v1"


def test_generate_requires_a_transcript(client, auth, owner_id, make_episode):
    episode_id = make_episode(owner_id)  # no transcript attached
    response = client.post(
        f"{API}/clips/generate", headers=auth, params={"episode_id": episode_id}, json={}
    )
    assert response.status_code == 409


def test_generate_dispatches_the_highlighter(client, auth, owner_id, make_episode, make_transcript, dispatch):
    episode_id = make_episode(owner_id, status="transcribed")
    make_transcript(episode_id)
    response = client.post(
        f"{API}/clips/generate", headers=auth, params={"episode_id": episode_id}, json={}
    )
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["episode_id"] == episode_id
    assert body["job_id"] is not None
    assert body["status"] == "pending"
    assert any(name == "tasks.ai.extract_highlights" for name, *_ in dispatch)


def test_generate_validates_duration_window(client, auth, owner_id, make_episode, make_transcript):
    episode_id = make_episode(owner_id, status="transcribed")
    make_transcript(episode_id)
    response = client.post(
        f"{API}/clips/generate",
        headers=auth,
        params={"episode_id": episode_id},
        json={"min_duration_seconds": 60, "max_duration_seconds": 30},
    )
    assert response.status_code == 422


def test_generate_404_for_unknown_episode(client, auth):
    response = client.post(
        f"{API}/clips/generate", headers=auth, params={"episode_id": 99999}, json={}
    )
    assert response.status_code == 404


def test_list_clips_scoped_to_owner_sorted_by_score(client, auth, owner_id, make_episode, make_clip, make_user):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, title="Low", virality_score=0.2)
    make_clip(episode_id, owner_id, title="High", virality_score=0.95)
    other = make_user("other@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    make_clip(make_episode(other_id), other_id, title="Theirs")

    response = client.get(f"{API}/clips", headers=auth)
    assert response.status_code == 200
    titles = [clip["title"] for clip in response.json()]
    assert titles == ["High", "Low"]


def test_list_clips_filters_by_min_score_and_episode(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, title="Keep", virality_score=0.8)
    make_clip(episode_id, owner_id, title="Drop", virality_score=0.1)
    response = client.get(f"{API}/clips", headers=auth, params={"min_score": 0.5})
    assert [c["title"] for c in response.json()] == ["Keep"]


def test_list_clips_favorite_filter(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, title="Starred", is_favorite=True)
    make_clip(episode_id, owner_id, title="Plain", is_favorite=False)
    response = client.get(f"{API}/clips", headers=auth, params={"favorite": "true"})
    assert [c["title"] for c in response.json()] == ["Starred"]


def test_list_clips_search_filter(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, title="Growth mindset", transcript_text="grow every day")
    make_clip(episode_id, owner_id, title="Cooking", transcript_text="recipes and food")
    response = client.get(f"{API}/clips", headers=auth, params={"search": "growth"})
    assert [c["title"] for c in response.json()] == ["Growth mindset"]


def test_caption_presets_returns_every_theme(client, auth):
    response = client.get(f"{API}/clips/presets", headers=auth)
    assert response.status_code == 200
    names = {preset["name"] for preset in response.json()}
    assert {"tiktok", "karaoke", "minimal", "neon", "bold_yellow"} <= names


def test_export_csv_returns_downloadable_file(client, auth, owner_id, make_episode, make_clip):
    """Regression: ``/clips/export`` used ``io.StringIO`` without importing io."""
    episode_id = make_episode(owner_id)
    make_clip(episode_id, owner_id, title="Exportable", hook="a, quoted \"hook\"")
    response = client.get(f"{API}/clips/export", headers=auth)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]

    lines = response.text.splitlines()
    header = lines[0].split(",")
    assert header[:4] == ["id", "episode_id", "title", "hook"]
    assert "is_favorite" in header
    assert any("Exportable" in line for line in lines[1:])


def test_export_csv_empty_library_has_header_only(client, auth):
    response = client.get(f"{API}/clips/export", headers=auth)
    assert response.status_code == 200
    assert response.text.strip().startswith("id,episode_id,title")
