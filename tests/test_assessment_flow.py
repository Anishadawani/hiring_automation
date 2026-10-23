"""Candidate flow, automatic scoring, time limits, results and grading."""
from datetime import datetime, timedelta, timezone

from app.models import AssessmentAttempt
from tests.conftest import apply_to, create_job, upload_resume
from tests.test_assessments import FT, MC, assessment_payload, make

R = "/api/recruiter"
C = "/api/candidate"


def setup(client, recruiter_headers, candidate_headers, stage="assessment", **overrides):
    job = create_job(client, recruiter_headers)
    assessment = make(client, recruiter_headers, job["id"], **overrides)
    upload_resume(client, candidate_headers)
    application = apply_to(client, candidate_headers, job["id"])
    if stage:
        r = client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": stage})
        assert r.status_code == 200
    return job, assessment, application


def start(client, headers, application, assessment):
    return client.post(f"{C}/applications/{application['id']}/assessments/{assessment['id']}/start", headers=headers)


def answer(client, headers, attempt_id, question_id, **body):
    return client.put(f"{C}/attempts/{attempt_id}/answers/{question_id}", headers=headers, json=body)


# ------------------------------------------------------------------- getting started


def test_tasks_appear_only_when_the_recruiter_opens_the_assessment_stage(client, recruiter_headers, candidate_headers):
    job, assessment, application = setup(client, recruiter_headers, candidate_headers, stage=None)
    assert client.get(f"{C}/assessments", headers=candidate_headers).json() == []
    assert start(client, candidate_headers, application, assessment).status_code == 409  # not their turn yet

    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "assessment"})
    tasks = client.get(f"{C}/assessments", headers=candidate_headers).json()
    assert len(tasks) == 1
    assert tasks[0]["status"] == "not_started" and tasks[0]["question_count"] == 2 and tasks[0]["attempt_id"] is None


def test_unpublished_assessments_are_invisible_and_cannot_be_started(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers, publish=False)
    assert client.get(f"{C}/assessments", headers=candidate_headers).json() == []
    assert start(client, candidate_headers, application, assessment).status_code == 404


def test_start_is_idempotent_and_hides_the_answer_key(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    first = start(client, candidate_headers, application, assessment)
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "in_progress" and body["seconds_remaining"] <= 30 * 60 and body["deadline"]
    assert body["instructions"].startswith("Answer every question")
    assert body["total_questions"] == 2 and body["answered_count"] == 0

    # No answer key, no rubric, no scores anywhere in the candidate's view.
    flat = str(body)
    assert "correct_option" not in flat and "rubric" not in flat and "score" not in flat
    assert set(body["questions"][0]) == {"id", "position", "prompt", "question_type", "options", "max_points"}

    again = start(client, candidate_headers, application, assessment)
    assert again.status_code == 200 and again.json()["attempt_id"] == body["attempt_id"]
    tasks = client.get(f"{C}/assessments", headers=candidate_headers).json()
    assert tasks[0]["status"] == "in_progress" and tasks[0]["attempt_id"] == body["attempt_id"]


def test_candidates_cannot_use_someone_elses_application_or_attempt(
    client, recruiter_headers, candidate_headers, other_candidate_headers
):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    started = start(client, candidate_headers, application, assessment).json()
    other = other_candidate_headers
    assert start(client, other, application, assessment).status_code == 404
    assert client.get(f"{C}/attempts/{started['attempt_id']}", headers=other).status_code == 404
    q = started["questions"][0]["id"]
    assert answer(client, other, started["attempt_id"], q, selected_option=1).status_code == 404
    assert client.post(f"{C}/attempts/{started['attempt_id']}/submit", headers=other).status_code == 404
    assert client.get(f"{C}/assessments", headers=other).json() == []


def test_recruiters_cannot_use_candidate_endpoints(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    assert client.get(f"{C}/assessments", headers=recruiter_headers).status_code == 403
    assert start(client, recruiter_headers, application, assessment).status_code == 403
    assert client.get(f"{C}/assessments").status_code == 401


# ------------------------------------------------------------------------ answering


def test_autosave_validation_and_overwrite(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    attempt = start(client, candidate_headers, application, assessment).json()
    aid, mc_id, ft_id = attempt["attempt_id"], attempt["questions"][0]["id"], attempt["questions"][1]["id"]

    assert answer(client, candidate_headers, aid, mc_id, selected_option=9).status_code == 422  # no such option
    assert answer(client, candidate_headers, aid, mc_id, answer_text="404").status_code == 422  # wrong field
    assert answer(client, candidate_headers, aid, ft_id, selected_option=1).status_code == 422
    assert answer(client, candidate_headers, aid, ft_id, answer_text="x" * 10_001).status_code == 422
    assert answer(client, candidate_headers, aid, 99999, selected_option=1).status_code == 404

    assert answer(client, candidate_headers, aid, mc_id, selected_option=0).status_code == 200
    assert answer(client, candidate_headers, aid, mc_id, selected_option=1).status_code == 200  # changed mind
    assert answer(client, candidate_headers, aid, ft_id, answer_text="A process has its own memory.").status_code == 200

    view = client.get(f"{C}/attempts/{aid}", headers=candidate_headers).json()
    assert view["answered_count"] == 2
    saved = {a["question_id"]: a for a in view["answers"]}
    assert saved[mc_id]["selected_option"] == 1 and saved[ft_id]["answer_text"].startswith("A process")

    # Clearing an answer works too.
    assert answer(client, candidate_headers, aid, mc_id).status_code == 200
    assert client.get(f"{C}/attempts/{aid}", headers=candidate_headers).json()["answered_count"] == 1


# ------------------------------------------------------------------------ submitting


def complete(client, candidate_headers, application, assessment, mc_choice=1, text="Processes are isolated; threads share memory."):
    attempt = start(client, candidate_headers, application, assessment).json()
    aid = attempt["attempt_id"]
    answer(client, candidate_headers, aid, attempt["questions"][0]["id"], selected_option=mc_choice)
    if text is not None:
        answer(client, candidate_headers, aid, attempt["questions"][1]["id"], answer_text=text)
    return aid, client.post(f"{C}/attempts/{aid}/submit", headers=candidate_headers)


def test_submit_scores_multiple_choice_and_leaves_free_text_for_a_person(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    aid, r = complete(client, candidate_headers, application, assessment)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "submitted" and body["seconds_remaining"] is None
    assert "score" not in str(body) and "correct" not in str(body)  # candidates never see results

    # Submitting twice is harmless; saving after submitting is not allowed.
    assert client.post(f"{C}/attempts/{aid}/submit", headers=candidate_headers).status_code == 200
    q = body["questions"][0]["id"]
    assert answer(client, candidate_headers, aid, q, selected_option=0).status_code == 409
    assert client.get(f"{C}/assessments", headers=candidate_headers).json()[0]["status"] == "submitted"

    results = client.get(f"{R}/applications/{application['id']}/assessment-results", headers=recruiter_headers).json()
    assert len(results) == 1
    res = results[0]
    assert res["status"] == "submitted" and res["pending_review"] == 1
    assert res["total_score"] == 2.0 and res["max_score"] == 8.0 and res["percentage"] is None  # not final yet
    mc, ft = res["answers"]
    assert mc["auto_graded"] is True and mc["score"] == 2.0 and mc["correct_option"] == 1 and mc["needs_review"] is False
    assert ft["auto_graded"] is False and ft["score"] is None and ft["needs_review"] is True
    assert [c["criterion"] for c in ft["rubric"]] == ["Correctness", "Reasoning", "Organisation"]

    # Advisory only: submitting never moves the candidate.
    detail = client.get(f"{R}/applications/{application['id']}", headers=recruiter_headers).json()
    assert detail["stage"] == "assessment"


def test_wrong_and_blank_answers_score_zero_without_needing_review(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    aid, r = complete(client, candidate_headers, application, assessment, mc_choice=0, text="   ")
    assert r.status_code == 200
    res = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    assert res["total_score"] == 0.0 and res["pending_review"] == 0 and res["percentage"] == 0.0
    assert all(a["score"] == 0.0 and not a["needs_review"] for a in res["answers"])


def test_unanswered_questions_are_recorded_as_zero(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    attempt = start(client, candidate_headers, application, assessment).json()
    assert client.post(f"{C}/attempts/{attempt['attempt_id']}/submit", headers=candidate_headers).status_code == 200
    res = client.get(f"/api/assessment-attempts/{attempt['attempt_id']}", headers=recruiter_headers).json()
    assert len(res["answers"]) == 2 and res["total_score"] == 0.0 and res["pending_review"] == 0


# ------------------------------------------------------------------------- grading


def test_grading_updates_totals_and_enforces_rules(client, recruiter_headers, other_recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    attempt = start(client, candidate_headers, application, assessment).json()
    aid = attempt["attempt_id"]
    mc_id, ft_id = attempt["questions"][0]["id"], attempt["questions"][1]["id"]
    answer(client, candidate_headers, aid, mc_id, selected_option=1)
    answer(client, candidate_headers, aid, ft_id, answer_text="Threads share memory inside a process.")

    # Cannot grade before the candidate submits.
    early = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    assert early["status"] == "in_progress" and early["total_score"] is None
    client.post(f"{C}/attempts/{aid}/submit", headers=candidate_headers)
    res = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    mc_answer, ft_answer = res["answers"]

    grade = lambda answer_id, **b: client.put(f"/api/assessment-attempts/{aid}/answers/{answer_id}/grade", headers=recruiter_headers, json=b)
    assert grade(mc_answer["answer_id"], score=1).status_code == 422  # auto-graded
    assert grade(ft_answer["answer_id"], score=7).status_code == 422  # above max_points (6)
    assert grade(ft_answer["answer_id"], score=-1).status_code == 422
    assert grade(99999, score=1).status_code == 404

    other = client.put(
        f"/api/assessment-attempts/{aid}/answers/{ft_answer['answer_id']}/grade",
        headers=other_recruiter_headers, json={"score": 3},
    )
    assert other.status_code == 404

    ok = grade(ft_answer["answer_id"], score=4.5, comment="  Good on memory, thin on trade-offs.  ")
    assert ok.status_code == 200
    done = ok.json()
    assert done["total_score"] == 6.5 and done["max_score"] == 8.0
    assert done["pending_review"] == 0 and done["percentage"] == 81.2
    graded = done["answers"][1]
    assert graded["score"] == 4.5 and graded["reviewer_comment"] == "Good on memory, thin on trade-offs."

    # A grader may change their mind.
    assert grade(ft_answer["answer_id"], score=5).json()["total_score"] == 7.0

    listing = client.get(f"/api/assessments/{assessment['id']}/attempts", headers=recruiter_headers).json()
    assert listing[0]["total_score"] == 7.0 and listing[0]["pending_review"] == 0
    assert client.get(f"/api/assessments/{assessment['id']}/attempts", headers=other_recruiter_headers).status_code == 404


def test_grading_a_blank_free_text_answer_is_refused(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    aid, _ = complete(client, candidate_headers, application, assessment, text=None)
    res = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    r = client.put(
        f"/api/assessment-attempts/{aid}/answers/{res['answers'][1]['answer_id']}/grade",
        headers=recruiter_headers, json={"score": 1},
    )
    assert r.status_code == 422


def test_candidates_cannot_see_or_grade_results(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    aid, _ = complete(client, candidate_headers, application, assessment)
    assert client.get(f"/api/assessment-attempts/{aid}", headers=candidate_headers).status_code == 403
    assert client.get(f"{R}/applications/{application['id']}/assessment-results", headers=candidate_headers).status_code == 403
    assert client.put(f"/api/assessment-attempts/{aid}/answers/1/grade", headers=candidate_headers, json={"score": 1}).status_code == 403


# ------------------------------------------------------------------------ time limit


def expire(db_session, attempt_id, minutes_ago):
    attempt = db_session.get(AssessmentAttempt, attempt_id)
    attempt.started_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    db_session.commit()


def test_time_limit_closes_the_attempt_and_keeps_saved_answers(client, recruiter_headers, candidate_headers, db_session):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers, time_limit_minutes=10)
    attempt = start(client, candidate_headers, application, assessment).json()
    aid, mc_id, ft_id = attempt["attempt_id"], attempt["questions"][0]["id"], attempt["questions"][1]["id"]
    answer(client, candidate_headers, aid, mc_id, selected_option=1)

    expire(db_session, aid, minutes_ago=20)  # well past the 10 minutes plus the grace period
    late = answer(client, candidate_headers, aid, ft_id, answer_text="Too late to count.")
    assert late.status_code == 409

    view = client.get(f"{C}/attempts/{aid}", headers=candidate_headers).json()
    assert view["status"] == "submitted"
    res = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    assert res["total_score"] == 2.0 and res["pending_review"] == 0  # saved MC answer counted, late text did not
    assert res["answers"][1]["answer_text"] is None
    submitted = datetime.fromisoformat(res["submitted_at"].replace("Z", "+00:00"))
    if submitted.tzinfo is None:  # SQLite hands back naive UTC timestamps
        submitted = submitted.replace(tzinfo=timezone.utc)
    assert submitted <= datetime.now(timezone.utc) - timedelta(minutes=9)  # recorded at the deadline
    events = client.get(f"{R}/dashboard", headers=recruiter_headers).json()["recent_activity"]
    assert any(e["action"] == "assessment_time_expired" for e in events)


def test_grace_period_allows_a_slightly_late_save(client, recruiter_headers, candidate_headers, db_session):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers, time_limit_minutes=10)
    attempt = start(client, candidate_headers, application, assessment).json()
    expire(db_session, attempt["attempt_id"], minutes_ago=10)  # just over the limit, inside the grace period
    ok = answer(client, candidate_headers, attempt["attempt_id"], attempt["questions"][0]["id"], selected_option=1)
    assert ok.status_code == 200


def test_expired_attempts_show_as_submitted_in_the_task_list(client, recruiter_headers, candidate_headers, db_session):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers, time_limit_minutes=10)
    attempt = start(client, candidate_headers, application, assessment).json()
    expire(db_session, attempt["attempt_id"], minutes_ago=60)
    assert client.get(f"{C}/assessments", headers=candidate_headers).json()[0]["status"] == "submitted"


def test_no_time_limit_means_no_deadline(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers, time_limit_minutes=None)
    body = start(client, candidate_headers, application, assessment).json()
    assert body["deadline"] is None and body["seconds_remaining"] is None


# ------------------------------------------------------- editing after candidates start


def test_changes_are_blocked_once_a_candidate_has_started(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"])
    upload_resume(client, candidate_headers)
    application = apply_to(client, candidate_headers, job["id"])
    client.patch(f"/api/recruiter/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "assessment"})
    started = client.post(
        f"/api/candidate/applications/{application['id']}/assessments/{body['id']}/start", headers=candidate_headers
    )
    assert started.status_code == 201

    url = f"/api/assessments/{body['id']}"
    assert client.put(url, headers=recruiter_headers, json=assessment_payload()).status_code == 409
    assert client.delete(url, headers=recruiter_headers).status_code == 409
    question_id = body["questions"][1]["id"]
    assert client.post(f"{url}/questions/{question_id}/rubric", headers=recruiter_headers).status_code == 409
    assert client.get(url, headers=recruiter_headers).json()["attempt_count"] == 1


# ----------------------------------------------------------------- stage and activity


def test_moving_the_application_on_closes_an_unfinished_assessment(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    attempt = start(client, candidate_headers, application, assessment).json()
    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "interview"})
    r = answer(client, candidate_headers, attempt["attempt_id"], attempt["questions"][0]["id"], selected_option=1)
    assert r.status_code == 409
    assert client.post(f"{C}/attempts/{attempt['attempt_id']}/submit", headers=candidate_headers).status_code == 409
    assert start(client, candidate_headers, application, assessment).status_code == 409


def test_a_submitted_assessment_stays_visible_after_the_stage_changes(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    complete(client, candidate_headers, application, assessment)
    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "interview"})
    tasks = client.get(f"{C}/assessments", headers=candidate_headers).json()
    assert len(tasks) == 1 and tasks[0]["status"] == "submitted"


def test_activity_log_records_events_without_answer_content(client, recruiter_headers, candidate_headers):
    _, assessment, application = setup(client, recruiter_headers, candidate_headers)
    aid, _ = complete(client, candidate_headers, application, assessment, text="SECRET ANSWER TEXT")
    res = client.get(f"/api/assessment-attempts/{aid}", headers=recruiter_headers).json()
    client.put(
        f"/api/assessment-attempts/{aid}/answers/{res['answers'][1]['answer_id']}/grade",
        headers=recruiter_headers, json={"score": 3, "comment": "SECRET COMMENT"},
    )
    events = client.get(f"{R}/dashboard", headers=recruiter_headers).json()["recent_activity"]
    actions = {e["action"] for e in events}
    assert {"assessment_created", "assessment_published", "assessment_started", "assessment_submitted", "assessment_graded"} <= actions
    assert "SECRET" not in str(events)
