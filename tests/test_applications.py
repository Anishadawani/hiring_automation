from tests.conftest import apply_to, create_job, upload_resume


def test_apply_requires_a_resume(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    r = client.post("/api/applications", headers=candidate_headers, json={"job_id": job["id"]})
    assert r.status_code == 400
    assert "resume" in r.json()["detail"].lower()


def test_apply_and_track(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers, title="Platform Engineer")
    upload_resume(client, candidate_headers)
    created = apply_to(client, candidate_headers, job["id"], "I would love this role.")
    assert created["stage"] == "applied" and created["job_title"] == "Platform Engineer"

    mine = client.get("/api/applications/mine", headers=candidate_headers).json()
    assert [a["id"] for a in mine] == [created["id"]]
    assert client.get(f"/api/applications/{created['id']}", headers=candidate_headers).status_code == 200

    opening = client.get(f"/api/openings/{job['id']}", headers=candidate_headers).json()
    assert opening["has_applied"] is True
    assert client.get(f"/api/jobs/{job['id']}", headers=recruiter_headers).json()["application_count"] == 1


def test_duplicate_application_rejected(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    apply_to(client, candidate_headers, job["id"])
    again = client.post("/api/applications", headers=candidate_headers, json={"job_id": job["id"]})
    assert again.status_code == 409


def test_cannot_apply_to_unpublished_or_missing_jobs(client, recruiter_headers, candidate_headers):
    draft = create_job(client, recruiter_headers, publish=False)
    upload_resume(client, candidate_headers)
    assert client.post("/api/applications", headers=candidate_headers, json={"job_id": draft["id"]}).status_code == 404
    assert client.post("/api/applications", headers=candidate_headers, json={"job_id": 9999}).status_code == 404


def test_recruiters_cannot_apply(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    assert client.post("/api/applications", headers=recruiter_headers, json={"job_id": job["id"]}).status_code == 403


def test_candidates_cannot_see_each_others_applications(
    client, recruiter_headers, candidate_headers, other_candidate_headers
):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    created = apply_to(client, candidate_headers, job["id"])
    url = f"/api/applications/{created['id']}"
    assert client.get(url, headers=other_candidate_headers).status_code == 404
    assert client.post(f"{url}/withdraw", headers=other_candidate_headers).status_code == 404
    assert client.get("/api/applications/mine", headers=other_candidate_headers).json() == []


def test_withdraw_flow(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    created = apply_to(client, candidate_headers, job["id"])
    r = client.post(f"/api/applications/{created['id']}/withdraw", headers=candidate_headers)
    assert r.status_code == 200 and r.json()["stage"] == "withdrawn"
    again = client.post(f"/api/applications/{created['id']}/withdraw", headers=candidate_headers)
    assert again.status_code == 409


def test_candidate_view_never_includes_internal_data(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    created = apply_to(client, candidate_headers, job["id"])
    client.post(f"/api/recruiter/applications/{created['id']}/screen", headers=recruiter_headers)
    client.post(
        f"/api/recruiter/applications/{created['id']}/notes", headers=recruiter_headers, json={"body": "internal"}
    )
    body = client.get(f"/api/applications/{created['id']}", headers=candidate_headers).json()
    assert set(body) == {"id", "job_id", "job_title", "stage", "cover_letter", "created_at", "updated_at"}