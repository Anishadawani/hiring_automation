import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import main, screener

GOOD = {
    "candidate_name": "Test User", "match_score": 72, "recommendation": "maybe",
    "matched_skills": ["Python"], "missing_skills": ["n8n"], "summary": "ok",
    "interview_questions": ["q1", "q2", "q3"],
}


class FakeClient:
    def __init__(self, text):
        self.messages = SimpleNamespace(create=lambda **kw: SimpleNamespace(
            content=[SimpleNamespace(type="text", text=text)]))


def test_parse_plain_json():
    assert screener.parse_result(json.dumps(GOOD)).match_score == 72


def test_parse_fenced_json():
    raw = "```json\n" + json.dumps(GOOD) + "\n```"
    assert screener.parse_result(raw).recommendation == "maybe"


def test_parse_rejects_garbage():
    with pytest.raises(screener.ScreeningError):
        screener.parse_result("no json here")


def test_parse_rejects_bad_score():
    bad = dict(GOOD, match_score=150)
    with pytest.raises(screener.ScreeningError):
        screener.parse_result(json.dumps(bad))


def test_screen_resume_with_fake_client():
    res = screener.screen_resume("resume text", "jd text", client=FakeClient(json.dumps(GOOD)))
    assert res.candidate_name == "Test User"


def test_extract_text_empty():
    with pytest.raises(screener.ScreeningError):
        screener.extract_text("a.txt", b"   ")


def test_endpoint(monkeypatch):
    monkeypatch.setattr(screener, "screen_resume",
                        lambda t, j, client=None: screener.ScreeningResult(**GOOD))
    c = TestClient(main.app)
    r = c.post("/screen", data={"job_description": "AI intern"},
               files={"resume": ("cv.txt", b"Python developer", "text/plain")})
    assert r.status_code == 200 and r.json()["match_score"] == 72
    assert c.get("/health").json() == {"status": "ok"}


def test_endpoint_api_key(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "secret")
    c = TestClient(main.app)
    r = c.post("/screen", data={"job_description": "x"},
               files={"resume": ("cv.txt", b"y", "text/plain")})
    assert r.status_code == 401
