"""Background job routes (list, detail, ownership, revoke)."""

API = "/api/v1"


def test_list_jobs_scoped_to_owner(client, auth, owner_id, make_episode, make_clip, make_job, make_user):
    episode_id = make_episode(owner_id)
    clip_id = make_clip(episode_id, owner_id)
    make_job(episode_id=episode_id, clip_id=clip_id, status="running")

    other = make_user("other@example.com")
    other_id = client.get(f"{API}/auth/me", headers=other["headers"]).json()["id"]
    other_episode = make_episode(other_id)
    make_job(episode_id=other_episode, status="pending")

    response = client.get(f"{API}/jobs", headers=auth)
    assert response.status_code == 200
    jobs = response.json()
    assert len(jobs) == 1
    assert jobs[0]["clip_id"] == clip_id


def test_read_job_refreshes_and_checks_ownership(client, auth, owner_id, make_episode, make_clip, make_job, make_user):
    episode_id = make_episode(owner_id)
    clip_id = make_clip(episode_id, owner_id)
    job_id = make_job(episode_id=episode_id, clip_id=clip_id, status="pending")

    response = client.get(f"{API}/jobs/{job_id}", headers=auth)
    assert response.status_code == 200
    assert response.json()["id"] == job_id

    # A different user must not be able to read it by id.
    other = make_user("spy@example.com")
    assert client.get(f"{API}/jobs/{job_id}", headers=other["headers"]).status_code == 404


def test_read_job_404_for_unknown(client, auth):
    assert client.get(f"{API}/jobs/123456", headers=auth).status_code == 404


def test_revoke_job_marks_it_failed(client, auth, owner_id, make_episode, make_clip, make_job):
    episode_id = make_episode(owner_id)
    clip_id = make_clip(episode_id, owner_id)
    job_id = make_job(episode_id=episode_id, clip_id=clip_id, status="running", task_id="abc")
    response = client.post(f"{API}/jobs/{job_id}/revoke", headers=auth)
    assert response.status_code == 200
    assert response.json()["status"] == "failure"


def test_revoke_job_404_for_other_user(client, auth, owner_id, make_episode, make_clip, make_job, make_user):
    episode_id = make_episode(owner_id)
    clip_id = make_clip(episode_id, owner_id)
    job_id = make_job(episode_id=episode_id, clip_id=clip_id, status="running", task_id="abc")
    other = make_user("spy@example.com")
    assert client.post(f"{API}/jobs/{job_id}/revoke", headers=other["headers"]).status_code == 404


def test_list_jobs_filters_by_type_and_status(client, auth, owner_id, make_episode, make_job):
    episode_id = make_episode(owner_id)
    make_job(episode_id=episode_id, job_type="render", status="success")
    make_job(episode_id=episode_id, job_type="transcription", status="running")
    response = client.get(f"{API}/jobs", headers=auth, params={"job_type": "render"})
    assert [j["job_type"] for j in response.json()] == ["render"]
