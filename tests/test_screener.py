
"""Tests for the original Claude-based screener helpers (parsing and text extraction).

The old stateless POST /screen endpoint was retired in Part 2; its two endpoint tests were
removed with it. Claude screening returns in Part 3 as a recruiter-only, human-reviewed step.
"""
import json
from types import SimpleNamespace

import pytest

from app import screener

GOOD = {
    "candidate_name": "Test User",
    "match_score": 72,
    "recommendation": "maybe",
    "matched_skills": ["Python"],
    "missing_skills": ["n8n"],
    "summary": "ok",
    "interview_questions": ["q1", "q2", "q3"],
}


class FakeClient:
    def __init__(self, text):
        self.messages = SimpleNamespace(
            create=lambda **kw: SimpleNamespace(
                content=[SimpleNamespace(type="text", text=text)]
            )
        )


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
    res = screener.screen_resume(
        "resume text",
        "jd text",
        client=FakeClient(json.dumps(GOOD)),
    )
    assert res.candidate_name == "Test User"


def test_extract_text_empty():
    with pytest.raises(screener.ScreeningError):
        screener.extract_text("a.txt", b"   ")
