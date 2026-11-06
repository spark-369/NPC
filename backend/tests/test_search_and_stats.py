"""Global search and dashboard analytics."""

API = "/api/v1"


def test_search_matches_episodes_and_clips(client, auth, owner_id, make_episode, make_clip):
    episode_id = make_episode(owner_id, title="Growth podcast")
    make_clip(episode_id, owner_id, title="Growth mindset clip", transcript_text="grow fast")
    response = client.get(f"{API}/search", headers=auth, params={"q": "growth"})
    assert response.status_code == 200
    body = response.json()
    assert body["query"] == "growth"
    assert body["total"] == 2
    assert {e["title"] for e in body["episodes"]} == {"Growth podcast"}
    assert {c["title"] for c in body["clips"]} == {"Growth mindset clip"}


def test_search_is_scoped_to_the_caller(client, auth, make_episode, make_user):
    other = make_user("other@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    make_episode(other_id, title="Growth secret")
    response = client.get(f"{API}/search", headers=auth, params={"q": "growth"})
    assert response.json()["total"] == 0


def test_search_requires_query(client, auth):
    assert client.get(f"{API}/search", headers=auth).status_code == 422


def test_search_requires_auth(client):
    assert client.get(f"{API}/search", params={"q": "x"}).status_code == 401


def test_stats_overview_aggregates(client, auth, owner_id, make_episode, make_clip, make_job):
    episode_id = make_episode(owner_id, file_size_bytes=4096)
    make_clip(episode_id, owner_id, virality_score=0.9, is_favorite=True)
    make_clip(episode_id, owner_id, virality_score=0.3)
    make_job(episode_id=episode_id, status="success")

    response = client.get(f"{API}/stats/overview", headers=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["episodes"]["total"] == 1
    assert body["episodes"]["total_source_bytes"] == 4096
    assert body["clips"]["total"] == 2
    assert body["clips"]["favorites"] == 1
    assert body["activity"]["renders_last_7_days"] >= 1
    assert len(body["top_clips"]) == 2
    assert body["top_clips"][0]["virality_score"] == 0.9


def test_stats_overview_empty_library(client, auth):
    body = client.get(f"{API}/stats/overview", headers=auth).json()
    assert body["episodes"]["total"] == 0
    assert body["clips"]["total"] == 0
    assert body["clips"]["average_duration_seconds"] == 0.0
