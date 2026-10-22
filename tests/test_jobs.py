from tests.conftest import JOB, create_job


def test_create_job_defaults_to_draft(client, recruiter_headers):
    r = client.post("/api/jobs", headers=recruiter_headers, json=JOB)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "draft"
    assert body["application_count"] == 0


def test_job_validation_and_skill_normalisation(client, recruiter_headers):
    short = {**JOB, "description": "too short"}
    assert client.post("/api/jobs", headers=recruiter_headers, json=short).status_code == 422
    archived = {**JOB, "status": "archived"}
    assert client.post("/api/jobs", headers=recruiter_headers, json=archived).status_code == 422

    messy = {**JOB, "required_skills": ["Python", " python ", ""], "preferred_skills": ["PYTHON", "Docker"]}
    body = client.post("/api/jobs", headers=recruiter_headers, json=messy).json()
    assert body["required_skills"] == ["Python"]
    assert body["preferred_skills"] == ["Docker"]


def test_cannot_publish_job_without_required_skills(client, recruiter_headers):
    job = create_job(client, recruiter_headers, publish=False, required_skills=[])
    r = client.patch(f"/api/jobs/{job['id']}/status", headers=recruiter_headers, json={"status": "open"})
    assert r.status_code == 422
    direct = client.post(
        "/api/jobs", headers=recruiter_headers, json={**JOB, "required_skills": [], "status": "open"}
    )
    assert direct.status_code == 422


def test_publish_edit_and_archive_flow(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    assert job["status"] == "open"

    updated = client.put(
        f"/api/jobs/{job['id']}", headers=recruiter_headers, json={**JOB, "title": "Senior Backend Engineer"}
    )
    assert updated.status_code == 200 and updated.json()["title"] == "Senior Backend Engineer"
    assert updated.json()["status"] == "open"

    archived = client.patch(f"/api/jobs/{job['id']}/status", headers=recruiter_headers, json={"status": "archived"})
    assert archived.json()["status"] == "archived"

    listing = client.get("/api/jobs?status=archived", headers=recruiter_headers).json()
    assert listing["total"] == 1


def test_open_job_cannot_lose_all_required_skills(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    r = client.put(f"/api/jobs/{job['id']}", headers=recruiter_headers, json={**JOB, "required_skills": []})
    assert r.status_code == 422


def test_recruiters_only_see_their_own_jobs(client, recruiter_headers, other_recruiter_headers):
    job = create_job(client, recruiter_headers)
    jid = job["id"]
    assert client.get(f"/api/jobs/{jid}", headers=other_recruiter_headers).status_code == 404
    assert client.put(f"/api/jobs/{jid}", headers=other_recruiter_headers, json=JOB).status_code == 404
    patch = client.patch(f"/api/jobs/{jid}/status", headers=other_recruiter_headers, json={"status": "archived"})
    assert patch.status_code == 404
    assert client.get("/api/jobs", headers=other_recruiter_headers).json() == {"items": [], "total": 0}


def test_candidates_cannot_manage_jobs(client, candidate_headers):
    assert client.post("/api/jobs", headers=candidate_headers, json=JOB).status_code == 403
    assert client.get("/api/jobs", headers=candidate_headers).status_code == 403
    assert client.post("/api/jobs", json=JOB).status_code == 401


def test_search_treats_wildcards_literally(client, recruiter_headers):
    create_job(client, recruiter_headers, publish=False, title="Backend Engineer")
    create_job(client, recruiter_headers, publish=False, title="100% Remote Role")
    result = client.get("/api/jobs", headers=recruiter_headers, params={"q": "%"}).json()
    assert [j["title"] for j in result["items"]] == ["100% Remote Role"]
    result = client.get("/api/jobs", headers=recruiter_headers, params={"q": "backend"}).json()
    assert result["total"] == 1


def test_candidates_see_only_open_jobs(client, recruiter_headers, candidate_headers):
    draft = create_job(client, recruiter_headers, publish=False, title="Draft Role")
    open_job = create_job(client, recruiter_headers, title="Open Role")
    archived = create_job(client, recruiter_headers, title="Old Role")
    client.patch(f"/api/jobs/{archived['id']}/status", headers=recruiter_headers, json={"status": "archived"})

    titles = [j["title"] for j in client.get("/api/openings", headers=candidate_headers).json()["items"]]
    assert titles == ["Open Role"]
    assert client.get(f"/api/openings/{open_job['id']}", headers=candidate_headers).status_code == 200
    assert client.get(f"/api/openings/{draft['id']}", headers=candidate_headers).status_code == 404
    assert client.get(f"/api/openings/{archived['id']}", headers=candidate_headers).status_code == 404


def test_openings_filters(client, recruiter_headers, candidate_headers):
    create_job(client, recruiter_headers, title="Data Engineer", location="Remote", employment_type="contract")
    create_job(client, recruiter_headers, title="Designer", location="Indore", employment_type="full_time")
    get = lambda **p: client.get("/api/openings", headers=candidate_headers, params=p).json()["total"]
    assert get(q="engineer") == 1
    assert get(location="indore") == 1
    assert get(employment_type="contract") == 1
    assert get() == 2


def test_candidate_view_hides_internal_fields(client, recruiter_headers, candidate_headers):
    create_job(client, recruiter_headers)
    item = client.get("/api/openings", headers=candidate_headers).json()["items"][0]
    assert "recruiter_id" not in item and "status" not in item and "application_count" not in item


def test_recruiters_cannot_use_candidate_openings(client, recruiter_headers):
    assert client.get("/api/openings", headers=recruiter_headers).status_code == 403