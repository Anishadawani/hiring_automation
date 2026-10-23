"""Assessment attempt rules: time limits, automatic scoring of multiple choice, totals.

Free-text answers are never scored automatically: a person grades them against the rubric.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import (
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    AttemptStatus,
    QuestionType,
    utcnow,
)

GRACE_SECONDS = 30  # allowance for network delay when the time limit runs out


def aware(dt: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes; treat them as UTC."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def deadline_for(attempt: AssessmentAttempt, assessment: Assessment) -> datetime | None:
    if not assessment.time_limit_minutes:
        return None
    return aware(attempt.started_at) + timedelta(minutes=assessment.time_limit_minutes)


def seconds_remaining(attempt: AssessmentAttempt, assessment: Assessment, now: datetime | None = None) -> int | None:
    deadline = deadline_for(attempt, assessment)
    if deadline is None:
        return None
    now = now or datetime.now(timezone.utc)
    return max(0, int((deadline - now).total_seconds()))


def is_expired(attempt: AssessmentAttempt, assessment: Assessment, now: datetime | None = None) -> bool:
    deadline = deadline_for(attempt, assessment)
    if deadline is None or attempt.status != AttemptStatus.in_progress:
        return False
    now = now or datetime.now(timezone.utc)
    return now > deadline + timedelta(seconds=GRACE_SECONDS)


def recompute_totals(attempt: AssessmentAttempt, answers: list[AssessmentAnswer]) -> None:
    attempt.total_score = round(sum(a.score for a in answers if a.score is not None), 2)


def pending_review(answers: list[AssessmentAnswer]) -> int:
    return sum(1 for a in answers if a.score is None)


def finalize_attempt(
    db: Session,
    attempt: AssessmentAttempt,
    questions: list[AssessmentQuestion],
    answers: list[AssessmentAnswer],
    submitted_at: datetime | None = None,
) -> list[AssessmentAnswer]:
    """Close an attempt: score multiple choice, zero blanks, leave real free text for a person."""
    by_question = {a.question_id: a for a in answers}
    for q in questions:
        answer = by_question.get(q.id)
        if answer is None:
            answer = AssessmentAnswer(attempt_id=attempt.id, question_id=q.id)
            db.add(answer)
            by_question[q.id] = answer
        if q.question_type == QuestionType.multiple_choice:
            correct = answer.selected_option is not None and answer.selected_option == q.correct_option
            answer.score = float(q.max_points) if correct else 0.0
        elif not (answer.answer_text or "").strip():
            answer.score = 0.0  # nothing to review
        else:
            answer.score = None  # waits for a human grader
    attempt.status = AttemptStatus.submitted
    attempt.submitted_at = submitted_at or utcnow()
    attempt.max_score = float(sum(q.max_points for q in questions))
    result = list(by_question.values())
    recompute_totals(attempt, result)
    return result


def percentage(attempt: AssessmentAttempt, answers: list[AssessmentAnswer]) -> float | None:
    if attempt.status != AttemptStatus.submitted or pending_review(answers) or not attempt.max_score:
        return None
    return round((attempt.total_score or 0) / attempt.max_score * 100, 1)
