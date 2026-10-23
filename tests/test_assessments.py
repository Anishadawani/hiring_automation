"""Recruiter-side assessment tests: create, validate, publish, ownership, rubrics (no real AI calls)."""
import json

import pytest

from app.main import app
from app.models import AssessmentKind
from app.routers.recruiter_ai import get_ai_client
from app.services import ai_review as air
from app.services import rubrics
from tests.conftest import create_job

MC = {
    "prompt": "Which HTTP status code means Not Found?",
    "question_type": "multiple_choice",
    "options": ["200", "404", "500"],
    "correct_option": 1,
    "max_points": 2,
}
FT = {
    "prompt": "Explain the difference between a process and a thread.",
    "question_type": "free_text",
    "max_points": 6,
    "rubric": [
        {"criterion": "Correctness", "description": "Accurate definitions", "points": 3},
        {"criterion": "Reasoning", "description": "Explains trade-offs", "points": 2},
        {"criterion": "Organisation", "description": "Easy to follow", "points": 1},
    ],
}


def assessment_payload(**overrides):
    return {
        "title": "Backend skills check",
        "kind": "technical",
        "instructions": "Answer every question. You may not use outside help.",
        "time_limit_minutes": 30,
        "questions": [MC, FT],
        **overrides,
    }


def make(client, headers, job_id, publish=True, **overrides):
    r = client.post(f"/api/jobs/{job_id}/assessments", headers=headers, json=assessment_payload(**overrides))
    assert r.status_code == 201, r.text
    body = r.json()
    if publish:
        r = client.patch(f"/api/assessments/{body['id']}/status", headers=headers, json={"is_published": True})
        assert r.status_code == 200, r.text
        body = r.json()
    return body


class FakeAI:
    def __init__(self, text=None, error=None):
        self.text, self.error, self.calls = text, error, []

    def complete(self, system, user, max_tokens=1800):
        self.calls.append((system, user))
        if self.error:
            raise self.error
        return air.AIResponse(text=self.text, model="claude-test-model")


def use_ai(fake):
    app.dependency_overrides[get_ai_client] = lambda: fake  # cleared by the client fixture
    return fake


# ------------------------------------------------------------------ create and read


def test_create_assessment_as_draft_with_questions(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"], publish=False)
    assert body["is_published"] is False and body["question_count"] == 2 and body["attempt_count"] == 0
    assert [q["position"] for q in body["questions"]] == [1, 2]
    assert body["questions"][0]["correct_option"] == 1  # recruiters see the answer key
    assert len(body["questions"][1]["rubric"]) == 3

    again = client.get(f"/api/assessments/{body['id']}", headers=recruiter_headers).json()
    assert again["questions"][1]["rubric"][0]["criterion"] == "Correctness"
    listing = client.get(f"/api/jobs/{job['id']}/assessments", headers=recruiter_headers).json()
    assert [a["id"] for a in listing] == [body["id"]]


@pytest.mark.parametrize(
    "question",
    [
        {**MC, "correct_option": 5},  # out of range
        {**MC, "correct_option": None},
        {**MC, "options": ["only one"], "correct_option": 0},
        {**MC, "options": ["same", "SAME"], "correct_option": 0},
        {**MC, "rubric": FT["rubric"]},  # multiple choice is auto-scored: no rubric
        {**FT, "options": ["a", "b"]},
        {**FT, "correct_option": 0},
        {**FT, "max_points": 5},  # rubric adds up to 6
        {**FT, "prompt": "Hi"},
        {**FT, "max_points": 0},
    ],
)
def test_invalid_questions_are_rejected(client, recruiter_headers, question):
    job = create_job(client, recruiter_headers)
    r = client.post(f"/api/jobs/{job['id']}/assessments", headers=recruiter_headers, json=assessment_payload(questions=[question]))
    assert r.status_code == 422


def test_title_and_time_limit_validation(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    url = f"/api/jobs/{job['id']}/assessments"
    assert client.post(url, headers=recruiter_headers, json=assessment_payload(title="Hi")).status_code == 422
    assert client.post(url, headers=recruiter_headers, json=assessment_payload(time_limit_minutes=1)).status_code == 422
    assert client.post(url, headers=recruiter_headers, json=assessment_payload(time_limit_minutes=999)).status_code == 422
    assert client.post(url, headers=recruiter_headers, json=assessment_payload(kind="quiz")).status_code == 422
    assert client.post(url, headers=recruiter_headers, json=assessment_payload(time_limit_minutes=None)).status_code == 201


# ------------------------------------------------------------------------- publish


def test_publishing_needs_questions_and_rubrics_for_free_text(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    empty = make(client, recruiter_headers, job["id"], publish=False, questions=[])
    r = client.patch(f"/api/assessments/{empty['id']}/status", headers=recruiter_headers, json={"is_published": True})
    assert r.status_code == 422 and "at least one question" in r.json()["detail"]

    no_rubric = make(client, recruiter_headers, job["id"], publish=False, questions=[{**FT, "rubric": []}])
    r = client.patch(f"/api/assessments/{no_rubric['id']}/status", headers=recruiter_headers, json={"is_published": True})
    assert r.status_code == 422 and "needs a grading rubric" in r.json()["detail"]


def test_publish_and_unpublish(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"])
    assert body["is_published"] is True
    off = client.patch(f"/api/assessments/{body['id']}/status", headers=recruiter_headers, json={"is_published": False})
    assert off.json()["is_published"] is False


def test_published_assessment_cannot_be_edited_into_an_invalid_state(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"])
    url = f"/api/assessments/{body['id']}"
    assert client.put(url, headers=recruiter_headers, json=assessment_payload(questions=[{**FT, "rubric": []}])).status_code == 422
    assert client.put(url, headers=recruiter_headers, json=assessment_payload(questions=[])).status_code == 422
    ok = client.put(url, headers=recruiter_headers, json=assessment_payload(title="Renamed check", questions=[MC]))
    assert ok.status_code == 200 and ok.json()["title"] == "Renamed check" and ok.json()["question_count"] == 1


def test_delete_unused_assessment(client, recruiter_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"], publish=False)
    assert client.delete(f"/api/assessments/{body['id']}", headers=recruiter_headers).status_code == 204
    assert client.get(f"/api/assessments/{body['id']}", headers=recruiter_headers).status_code == 404


# ----------------------------------------------------------------- access control


def test_recruiters_only_reach_their_own_assessments(client, recruiter_headers, other_recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers)
    body = make(client, recruiter_headers, job["id"])
    aid = body["id"]
    other = other_recruiter_headers
    assert client.get(f"/api/jobs/{job['id']}/assessments", headers=other).status_code == 404
    assert client.post(f"/api/jobs/{job['id']}/assessments", headers=other, json=assessment_payload()).status_code == 404
    assert client.get(f"/api/assessments/{aid}", headers=other).status_code == 404
    assert client.put(f"/api/assessments/{aid}", headers=other, json=assessment_payload()).status_code == 404
    assert client.patch(f"/api/assessments/{aid}/status", headers=other, json={"is_published": False}).status_code == 404
    assert client.delete(f"/api/assessments/{aid}", headers=other).status_code == 404
    assert client.get(f"/api/assessments/{aid}/attempts", headers=other).status_code == 404

    assert client.get(f"/api/assessments/{aid}", headers=candidate_headers).status_code == 403
    assert client.post(f"/api/jobs/{job['id']}/assessments", headers=candidate_headers, json=assessment_payload()).status_code == 403
    assert client.get(f"/api/assessments/{aid}").status_code == 401


# ------------------------------------------------------------------------- rubrics


def draft_with_free_text(client, headers, kind="technical", max_points=10):
    job = create_job(client, headers)
    body = make(
        client, headers, job["id"], publish=False, kind=kind,
        questions=[MC, {"prompt": "Describe a time you resolved a conflict.", "question_type": "free_text", "max_points": max_points}],
    )
    return body, body["questions"][1]["id"], body["questions"][0]["id"]


def test_rubric_without_an_api_key_is_an_honest_template(client, recruiter_headers):
    body, ft_id, _ = draft_with_free_text(client, recruiter_headers)
    r = client.post(f"/api/assessments/{body['id']}/questions/{ft_id}/rubric", headers=recruiter_headers)
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "template" and out["ai_used"] is False and "not configured" in out["notice"]
    assert sum(c["points"] for c in out["rubric"]) == 10

    saved = client.get(f"/api/assessments/{body['id']}", headers=recruiter_headers).json()
    assert sum(c["points"] for c in saved["questions"][1]["rubric"]) == 10
    publish = client.patch(f"/api/assessments/{body['id']}/status", headers=recruiter_headers, json={"is_published": True})
    assert publish.status_code == 200  # a generated rubric satisfies the publish rule


def test_behavioral_template_uses_star_criteria(client, recruiter_headers):
    body, ft_id, _ = draft_with_free_text(client, recruiter_headers, kind="behavioral", max_points=10)
    out = client.post(f"/api/assessments/{body['id']}/questions/{ft_id}/rubric", headers=recruiter_headers).json()
    assert [c["criterion"] for c in out["rubric"]] == ["Situation and task", "Actions taken", "Results", "Reflection"]


def test_multiple_choice_and_missing_questions_have_no_rubric(client, recruiter_headers):
    body, ft_id, mc_id = draft_with_free_text(client, recruiter_headers)
    base = f"/api/assessments/{body['id']}/questions"
    assert client.post(f"{base}/{mc_id}/rubric", headers=recruiter_headers).status_code == 422
    assert client.post(f"{base}/99999/rubric", headers=recruiter_headers).status_code == 404


def test_claude_rubric_is_checked_and_points_are_rescaled(client, recruiter_headers):
    body, ft_id, _ = draft_with_free_text(client, recruiter_headers, max_points=10)
    reply = json.dumps({"criteria": [
        {"criterion": "Specific situation", "description": "A real, concrete example", "points": 5},
        {"criterion": "Own actions", "description": "What the candidate did", "points": 10},
        {"criterion": "Outcome", "description": "Concrete result", "points": 5},
    ]})  # adds up to 20, but the question is worth 10
    fake = use_ai(FakeAI(reply))
    out = client.post(f"/api/assessments/{body['id']}/questions/{ft_id}/rubric", headers=recruiter_headers).json()
    assert out["source"] == "claude" and out["ai_used"] is True and out["notice"] is None
    assert sum(c["points"] for c in out["rubric"]) == 10 and all(c["points"] >= 1 for c in out["rubric"])
    assert [c["points"] for c in out["rubric"]] == [3, 5, 2]
    system, user = fake.calls[0]
    assert "<question>" in user and "native-like English" in system  # fairness rule is in the prompt


@pytest.mark.parametrize(
    "fake, expected",
    [
        (FakeAI(error=air.AIUnavailable("The AI service timed out. Please try again.")), "timed out"),
        (FakeAI(text="not json"), "expected format"),
        (FakeAI(text=json.dumps({"criteria": [{"criterion": "Only one", "description": "", "points": 10}]})), "usable set"),
        (FakeAI(text=json.dumps({"criteria": [
            {"criterion": "Age and gender fit", "description": "Judges age", "points": 5},
            {"criterion": "Actions", "description": "What was done", "points": 5}]})), "protected characteristic"),
    ],
)
def test_bad_ai_rubrics_fall_back_to_the_template(client, recruiter_headers, fake, expected):
    body, ft_id, _ = draft_with_free_text(client, recruiter_headers)
    use_ai(fake)
    r = client.post(f"/api/assessments/{body['id']}/questions/{ft_id}/rubric", headers=recruiter_headers)
    assert r.status_code == 200
    out = r.json()
    assert out["source"] == "template" and out["ai_used"] is False
    assert expected in out["notice"] and "template rubric was used" in out["notice"]
    assert sum(c["points"] for c in out["rubric"]) == 10


def test_hourly_ai_rubric_limit(client, recruiter_headers, monkeypatch):
    monkeypatch.setattr(rubrics, "MAX_AI_RUBRICS_PER_HOUR", 1)
    body, ft_id, _ = draft_with_free_text(client, recruiter_headers, max_points=10)
    good = json.dumps({"criteria": [
        {"criterion": "A", "description": "", "points": 5}, {"criterion": "B", "description": "", "points": 5}]})
    fake = use_ai(FakeAI(good))
    url = f"/api/assessments/{body['id']}/questions/{ft_id}/rubric"
    assert client.post(url, headers=recruiter_headers).status_code == 200
    assert client.post(url, headers=recruiter_headers).status_code == 429
    assert len(fake.calls) == 1


# ------------------------------------------------------------------- unit tests


def test_split_points_always_adds_up_and_gives_everyone_a_point():
    for total in range(1, 30):
        for weights in ([1], [4, 3, 2], [2, 4, 3, 1], [5, 5], [10, 1, 1]):
            if total < len(weights):
                with pytest.raises(ValueError):
                    rubrics.split_points(total, weights)
                continue
            points = rubrics.split_points(total, weights)
            assert sum(points) == total and min(points) >= 1 and len(points) == len(weights)


def test_template_rubrics_fit_any_point_value():
    for kind in AssessmentKind:
        for total in (1, 2, 3, 5, 10, 100):
            rubric = rubrics.template_rubric(kind, total)
            assert sum(c.points for c in rubric) == total
