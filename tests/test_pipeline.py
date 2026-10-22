from tests.conftest import PASSWORD, apply_to, create_job, make_headers, upload_resume

R = "/api/recruiter"


def setup_application(client, recruiter_headers, candidate_headers, resume="Python and FastAPI with Docker", **job):
    created_job = create_job(client, recruiter_headers, **job)
    upload_resume(client, candidate_headers, resume)
    application = apply_to(client, candidate_headers, created_job["id"])
    return created_job, application


def test_recruiter_sees_only_applicants_to_their_own_jobs(
    client, recruiter_headers, other_recruiter_headers, candidate_headers
):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    mine = client.get(f"{R}/applications", headers=recruiter_headers).json()
    assert mine["total"] == 1 and mine["items"][0]["id"] == application["id"]
    assert client.get(f"{R}/applications", headers=other_recruiter_headers).json() == {"items": [], "total": 0}


def test_other_recruiters_get_404_on_every_application_action(
    client, recruiter_headers, other_recruiter_headers, candidate_headers
):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    base = f"{R}/applications/{application['id']}"
    h = other_recruiter_headers
    assert client.get(base, headers=h).status_code == 404
    assert client.patch(f"{base}/stage", headers=h, json={"stage": "shortlisted"}).status_code == 404
    assert client.post(f"{base}/notes", headers=h, json={"body": "x"}).status_code == 404
    assert client.post(f"{base}/screen", headers=h).status_code == 404
    assert client.get(f"{base}/resume", headers=h).status_code == 404


def test_candidates_cannot_use_recruiter_endpoints(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    for path in ("/applications", f"/applications/{application['id']}", "/dashboard", "/scoring-method"):
        assert client.get(R + path, headers=candidate_headers).status_code == 403
    assert client.get(R + "/applications").status_code == 401


def test_rules_screening_is_advisory_and_explainable(client, recruiter_headers, candidate_headers):
    _, application = setup_application(
        client, recruiter_headers, candidate_headers, resume="Python and FastAPI developer"
    )
    r = client.post(f"{R}/applications/{application['id']}/screen", headers=recruiter_headers)
    assert r.status_code == 201
    body = r.json()
    assert body["mode"] == "rules"
    assert body["ai_model"] is None and body["ai_summary"] is None  # no AI was involved
    assert body["matched_skills"] == ["Python", "FastAPI"]
    assert body["missing_skills"] == []
    assert body["match_score"] == 80.0  # (0.60 x 1.0 + 0.15 x 0.0) / 0.75: preferred Docker not found
    assert all(e["snippet"] for e in body["evidence"] if e["source"] == "resume")
    assert "advisory" in body["advisory"].lower()

    detail = client.get(f"{R}/applications/{application['id']}", headers=recruiter_headers).json()
    assert detail["stage"] == "applied"  # screening never moves a candidate
    assert detail["latest_score"] == body["match_score"]
    assert len(detail["screenings"]) == 1


def test_identical_resumes_get_identical_scores_regardless_of_name(
    client, recruiter_headers, candidate_headers
):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers, "Python developer")
    first = apply_to(client, candidate_headers, job["id"])

    client.post(
        "/api/auth/register",
        json={"email": "zoe@example.com", "password": PASSWORD, "full_name": "Zoë Ñandú", "role": "candidate"},
    )
    token = client.post("/api/auth/login", json={"email": "zoe@example.com", "password": PASSWORD})
    zoe = {"Authorization": f"Bearer {token.json()['access_token']}"}
    upload_resume(client, zoe, "Python developer")
    second = apply_to(client, zoe, job["id"])

    s1 = client.post(f"{R}/applications/{first['id']}/screen", headers=recruiter_headers).json()
    s2 = client.post(f"{R}/applications/{second['id']}/screen", headers=recruiter_headers).json()
    assert s1["match_score"] == s2["match_score"]


def test_screening_needs_data_and_is_blocked_after_withdrawal(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    client.delete("/api/candidate/resume", headers=candidate_headers)
    r = client.post(f"{R}/applications/{application['id']}/screen", headers=recruiter_headers)
    assert r.status_code == 422

    client.post(f"/api/applications/{application['id']}/withdraw", headers=candidate_headers)
    r = client.post(f"{R}/applications/{application['id']}/screen", headers=recruiter_headers)
    assert r.status_code == 409


def test_filters_and_sorting(client, recruiter_headers, candidate_headers, other_candidate_headers):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers, "Python and FastAPI")
    upload_resume(client, other_candidate_headers, "Python only")
    strong = apply_to(client, candidate_headers, job["id"])
    weak = apply_to(client, other_candidate_headers, job["id"])
    for a in (strong, weak):
        client.post(f"{R}/applications/{a['id']}/screen", headers=recruiter_headers)

    get = lambda **p: client.get(f"{R}/applications", headers=recruiter_headers, params=p).json()
    by_score = get(sort="score")
    assert [i["id"] for i in by_score["items"]] == [strong["id"], weak["id"]]
    assert [i["id"] for i in get(min_score=75)["items"]] == [strong["id"]]  # strong=80.0, weak=40.0
    assert get(stage="interview")["total"] == 0
    assert get(q="other.candidate")["total"] == 1
    assert get(job_id=job["id"])["total"] == 2
    assert get(limit=1)["total"] == 2 and len(get(limit=1)["items"]) == 1


def test_unscreened_applicants_sort_last_and_have_no_score(client, recruiter_headers, candidate_headers, other_candidate_headers):
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    upload_resume(client, other_candidate_headers)
    unscreened = apply_to(client, candidate_headers, job["id"])
    screened = apply_to(client, other_candidate_headers, job["id"])
    client.post(f"{R}/applications/{screened['id']}/screen", headers=recruiter_headers)
    items = client.get(f"{R}/applications", headers=recruiter_headers, params={"sort": "score"}).json()["items"]
    assert [i["id"] for i in items] == [screened["id"], unscreened["id"]]
    assert items[1]["latest_score"] is None


def test_rejection_requires_a_written_reason(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    url = f"{R}/applications/{application['id']}/stage"
    assert client.patch(url, headers=recruiter_headers, json={"stage": "rejected"}).status_code == 422
    assert client.patch(url, headers=recruiter_headers, json={"stage": "rejected", "reason": "   "}).status_code == 422

    ok = client.patch(url, headers=recruiter_headers, json={"stage": "rejected", "reason": "Role needs more Go."})
    assert ok.status_code == 200
    body = ok.json()
    assert body["stage"] == "rejected" and body["decision_reason"] == "Role needs more Go."
    assert body["decided_by_name"] == "Test User" and body["decided_at"] is not None

    # Reopening clears the decision record (the history stays in the activity log).
    back = client.patch(url, headers=recruiter_headers, json={"stage": "under_review"}).json()
    assert back["decision_reason"] is None and back["decided_at"] is None


def test_shortlisting_records_who_decided(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    body = client.patch(
        f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "shortlisted"}
    ).json()
    assert body["stage"] == "shortlisted" and body["decided_by_name"] is not None


def test_recruiters_cannot_set_system_stages_or_edit_withdrawn(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    url = f"{R}/applications/{application['id']}/stage"
    assert client.patch(url, headers=recruiter_headers, json={"stage": "withdrawn"}).status_code == 422
    assert client.patch(url, headers=recruiter_headers, json={"stage": "applied"}).status_code == 422
    assert client.patch(url, headers=recruiter_headers, json={"stage": "nonsense"}).status_code == 422

    client.post(f"/api/applications/{application['id']}/withdraw", headers=candidate_headers)
    assert client.patch(url, headers=recruiter_headers, json={"stage": "interview"}).status_code == 409


def test_notes(client, recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    url = f"{R}/applications/{application['id']}/notes"
    assert client.post(url, headers=recruiter_headers, json={"body": "   "}).status_code == 422
    created = client.post(url, headers=recruiter_headers, json={"body": "Strong API portfolio."})
    assert created.status_code == 201 and created.json()["author_name"] == "Test User"
    detail = client.get(f"{R}/applications/{application['id']}", headers=recruiter_headers).json()
    assert [n["body"] for n in detail["notes"]] == ["Strong API portfolio."]


def test_resume_download(client, recruiter_headers, other_recruiter_headers, candidate_headers):
    _, application = setup_application(client, recruiter_headers, candidate_headers)
    url = f"{R}/applications/{application['id']}/resume"
    r = client.get(url, headers=recruiter_headers)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert "attachment" in r.headers["content-disposition"]
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.content.startswith(b"%PDF-")
    assert client.get(url, headers=other_recruiter_headers).status_code == 404


def test_dashboard_shows_real_counts_only(client, recruiter_headers, candidate_headers):
    empty = client.get(f"{R}/dashboard", headers=recruiter_headers).json()
    assert empty["total_applications"] == 0 and empty["recent_activity"] == []
    assert all(v == 0 for v in empty["jobs_by_status"].values())

    job, application = setup_application(client, recruiter_headers, candidate_headers)
    create_job(client, recruiter_headers, publish=False)
    client.patch(
        f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "interview"}
    )
    data = client.get(f"{R}/dashboard", headers=recruiter_headers).json()
    assert data["jobs_by_status"] == {"draft": 1, "open": 1, "archived": 0}
    assert data["applications_by_stage"]["interview"] == 1
    assert data["total_applications"] == 1
    actions = {a["action"] for a in data["recent_activity"]}
    assert {"job_created", "application_submitted", "stage_changed"} <= actions


def test_scoring_method_is_documented(client, recruiter_headers):
    body = client.get(f"{R}/scoring-method", headers=recruiter_headers).json()
    assert "formula" in body and "required_scoring" not in body and "required_skills" in body["components"] and body["limits"]