from datetime import date

import pytest

from app.services.scoring import find_skill, score_application, total_years_experience

TODAY = date(2026, 1, 1)


def score(**overrides):
    base = dict(
        required_skills=["Python", "FastAPI"],
        preferred_skills=[],
        min_years_experience=0,
        resume_text="",
        profile_skills=[],
        experience=[],
        today=TODAY,
    )
    base.update(overrides)
    return score_application(**base)


def test_all_required_skills_found_scores_100():
    result = score(resume_text="Built APIs with Python and FastAPI.")
    assert result.score == 100.0
    assert result.missing_skills == []


def test_partial_match_and_missing_skills():
    result = score(resume_text="Python developer.")
    assert result.score == 50.0
    assert result.matched_skills == ["Python"]
    assert result.missing_skills == ["FastAPI"]


def test_no_match_scores_zero():
    assert score(resume_text="Chef and baker.").score == 0.0


def test_matching_uses_whole_terms():
    assert find_skill("Java", "I know JavaScript well", []) is None
    assert find_skill("Java", "Java, Kotlin", []) is not None
    assert find_skill("C++", "Wrote C++ daily", []) is not None
    assert find_skill("C", "Wrote C++ daily", []) is None
    assert find_skill("Node.js", "Backend in node.js and Go", []) is not None
    assert find_skill("python", "PYTHON expert", []) is not None


def test_postgres_does_not_match_postgresql():
    assert find_skill("Postgres", "Used PostgreSQL", []) is None


def test_evidence_snippet_comes_from_the_resume():
    hit = find_skill("FastAPI", "Shipped three services using FastAPI and Docker in 2024.", [])
    assert hit["source"] == "resume"
    assert "FastAPI" in hit["snippet"]


def test_profile_only_skill_is_labelled_self_declared():
    hit = find_skill("Python", "", ["python"])
    assert hit["source"].startswith("profile")
    assert hit["snippet"] is None


def test_weights_are_renormalised_when_components_missing():
    # Only required skills defined: ratio alone decides the score.
    assert score(resume_text="Python only").score == 50.0


def test_full_weighting_with_all_components():
    result = score(
        resume_text="Python and FastAPI and Docker",
        preferred_skills=["Docker", "Redis"],
        min_years_experience=4,
        experience=[{"start_date": "2024-01-01", "end_date": "2026-01-01"}],
    )
    # 0.60*1.0 + 0.15*0.5 + 0.25*0.5 = 0.80
    assert result.score == 80.0
    components = result.breakdown["components"]
    assert components["required_skills"]["points"] == 60.0
    assert components["preferred_skills"]["points"] == 7.5
    assert components["experience"]["points"] == 12.5
    assert result.breakdown["missing_preferred"] == ["Redis"]
    assert "Redis" not in result.missing_skills


def test_overlapping_jobs_are_merged():
    years = total_years_experience(
        [
            {"start_date": "2020-01-01", "end_date": "2022-01-01"},
            {"start_date": "2021-01-01", "end_date": "2023-01-01"},
        ],
        TODAY,
    )
    assert years == 3.0


def test_ongoing_job_counts_until_today_and_future_jobs_are_ignored():
    assert total_years_experience([{"start_date": "2024-01-01", "end_date": None}], TODAY) == 2.0
    assert total_years_experience([{"start_date": "2030-01-01", "end_date": None}], TODAY) == 0.0


def test_bad_dates_are_skipped_not_fatal():
    assert total_years_experience([{"start_date": "nonsense"}, {}], TODAY) == 0.0


def test_job_without_required_skills_cannot_be_scored():
    with pytest.raises(ValueError):
        score(required_skills=[])


def test_score_is_deterministic():
    a = score(resume_text="Python FastAPI")
    b = score(resume_text="Python FastAPI")
    assert a == b