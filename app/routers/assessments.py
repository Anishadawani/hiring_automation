"""Recruiter assessment management, rubrics, results and grading.

A recruiter can only see and change assessments on their own jobs. Free-text answers are graded by
a person. Nothing here changes an application's stage.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_recruiter
from app.models import (
    ActivityLog,
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    Application,
    AttemptStatus,
    Job,
    QuestionType,
    User,
)
from app.routers.recruiter_ai import get_ai_client
from app.schemas.assessments import (
    AnswerResult,
    AssessmentDetail,
    AssessmentIn,
    AssessmentSummary,
    AttemptResult,
    AttemptSummary,
    GradeIn,
    QuestionIn,
    QuestionOut,
    RubricCriterion,
    RubricOut,
    StatusUpdate,
)
from app.services import ai_review as air
from app.services import assessments as svc
from app.services import rubrics
from app.services.access import owned_application
from app.services.activity import log_activity

router = APIRouter(prefix="/api", tags=["assessments (recruiter)"])


# ------------------------------------------------------------------------- helpers


def _owned_job(db: Session, job_id: int, recruiter: User) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.recruiter_id == recruiter.id))
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


def _owned_assessment(db: Session, assessment_id: int, recruiter: User) -> Assessment:
    assessment = db.scalar(
        select(Assessment)
        .join(Job, Assessment.job_id == Job.id)
        .where(Assessment.id == assessment_id, Job.recruiter_id == recruiter.id)
    )
    if assessment is None:
        raise HTTPException(404, "Assessment not found.")
    return assessment


def _attempt_count(db: Session, assessment_id: int) -> int:
    return db.scalar(
        select(func.count()).select_from(AssessmentAttempt).where(AssessmentAttempt.assessment_id == assessment_id)
    ) or 0


def _require_no_attempts(db: Session, assessment: Assessment) -> None:
    if _attempt_count(db, assessment.id):
        raise HTTPException(
            409, "Candidates have already started this assessment, so its questions can no longer be changed."
        )


def _ordered_questions(db: Session, assessment_id: int) -> list[AssessmentQuestion]:
    return list(
        db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.assessment_id == assessment_id)
            .order_by(AssessmentQuestion.position, AssessmentQuestion.id)
        ).all()
    )


def _question_out(q: AssessmentQuestion) -> QuestionOut:
    return QuestionOut(
        id=q.id,
        position=q.position,
        prompt=q.prompt,
        question_type=q.question_type,
        options=list(q.options or []),
        correct_option=q.correct_option,
        max_points=q.max_points,
        rubric=[RubricCriterion.model_validate(c) for c in (q.rubric or [])],
    )


def _summary_fields(db: Session, a: Assessment, questions: list[AssessmentQuestion]) -> dict:
    return dict(
        id=a.id,
        job_id=a.job_id,
        title=a.title,
        kind=a.kind,
        is_published=a.is_published,
        time_limit_minutes=a.time_limit_minutes,
        question_count=len(questions),
        attempt_count=_attempt_count(db, a.id),
        created_at=a.created_at,
    )


def _detail(db: Session, a: Assessment) -> AssessmentDetail:
    questions = _ordered_questions(db, a.id)
    return AssessmentDetail(
        **_summary_fields(db, a, questions),
        instructions=a.instructions or "",
        questions=[_question_out(q) for q in questions],
    )


def _replace_questions(db: Session, assessment: Assessment, items: list[QuestionIn]) -> None:
    db.execute(delete(AssessmentQuestion).where(AssessmentQuestion.assessment_id == assessment.id))
    for position, item in enumerate(items, start=1):
        db.add(
            AssessmentQuestion(
                assessment_id=assessment.id,
                position=position,
                prompt=item.prompt,
                question_type=item.question_type,
                options=item.options,
                correct_option=item.correct_option,
                max_points=item.max_points,
                rubric=[c.model_dump() for c in item.rubric],
            )
        )
    db.flush()


def _publish_problems(questions: list[AssessmentQuestion]) -> list[str]:
    problems: list[str] = []
    if not questions:
        problems.append("Add at least one question.")
    for q in questions:
        if q.question_type == QuestionType.free_text and not q.rubric:
            problems.append(f"Question {q.position} is free text and needs a grading rubric.")
    return problems


# ------------------------------------------------------------------ manage assessments


@router.get("/jobs/{job_id}/assessments", response_model=list[AssessmentSummary])
def list_assessments(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job = _owned_job(db, job_id, recruiter)
    assessments = db.scalars(
        select(Assessment).where(Assessment.job_id == job.id).order_by(Assessment.created_at.desc(), Assessment.id.desc())
    ).all()
    return [AssessmentSummary(**_summary_fields(db, a, _ordered_questions(db, a.id))) for a in assessments]


@router.post("/jobs/{job_id}/assessments", response_model=AssessmentDetail, status_code=201)
def create_assessment(
    job_id: int,
    payload: AssessmentIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    job = _owned_job(db, job_id, recruiter)
    assessment = Assessment(
        job_id=job.id,
        created_by_id=recruiter.id,
        title=payload.title,
        kind=payload.kind,
        instructions=payload.instructions,
        time_limit_minutes=payload.time_limit_minutes,
        is_published=False,
    )
    db.add(assessment)
    db.flush()
    _replace_questions(db, assessment, payload.questions)
    log_activity(db, recruiter.id, "assessment_created", job_id=job.id, detail={"assessment_id": assessment.id})
    db.commit()
    return _detail(db, assessment)


@router.get("/assessments/{assessment_id}", response_model=AssessmentDetail)
def get_assessment(assessment_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    return _detail(db, _owned_assessment(db, assessment_id, recruiter))


@router.put("/assessments/{assessment_id}", response_model=AssessmentDetail)
def update_assessment(
    assessment_id: int,
    payload: AssessmentIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    assessment = _owned_assessment(db, assessment_id, recruiter)
    _require_no_attempts(db, assessment)
    if assessment.is_published:
        # Re-check on a throwaway basis so a published assessment can never become invalid.
        for position, q in enumerate(payload.questions, start=1):
            if q.question_type == QuestionType.free_text and not q.rubric:
                raise HTTPException(422, f"Question {position} is free text and needs a grading rubric.")
        if not payload.questions:
            raise HTTPException(422, "A published assessment needs at least one question.")
    assessment.title = payload.title
    assessment.kind = payload.kind
    assessment.instructions = payload.instructions
    assessment.time_limit_minutes = payload.time_limit_minutes
    _replace_questions(db, assessment, payload.questions)
    log_activity(db, recruiter.id, "assessment_updated", job_id=assessment.job_id, detail={"assessment_id": assessment.id})
    db.commit()
    return _detail(db, assessment)


@router.patch("/assessments/{assessment_id}/status", response_model=AssessmentDetail)
def set_published(
    assessment_id: int,
    payload: StatusUpdate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    assessment = _owned_assessment(db, assessment_id, recruiter)
    if payload.is_published and not assessment.is_published:
        problems = _publish_problems(_ordered_questions(db, assessment.id))
        if problems:
            raise HTTPException(422, " ".join(problems))
    if payload.is_published != assessment.is_published:
        assessment.is_published = payload.is_published
        log_activity(
            db, recruiter.id, "assessment_published" if payload.is_published else "assessment_unpublished",
            job_id=assessment.job_id, detail={"assessment_id": assessment.id},
        )
        db.commit()
    return _detail(db, assessment)


@router.delete("/assessments/{assessment_id}", status_code=204)
def delete_assessment(assessment_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    assessment = _owned_assessment(db, assessment_id, recruiter)
    if _attempt_count(db, assessment.id):
        raise HTTPException(409, "Candidates have already started this assessment, so it cannot be deleted. Unpublish it instead.")
    job_id = assessment.job_id
    db.delete(assessment)
    log_activity(db, recruiter.id, "assessment_deleted", job_id=job_id, detail={"assessment_id": assessment_id})
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------------- rubrics


@router.post("/assessments/{assessment_id}/questions/{question_id}/rubric", response_model=RubricOut)
def generate_question_rubric(
    assessment_id: int,
    question_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
    ai: air.ClaudeClient | None = Depends(get_ai_client),
):
    """Generate a rubric for one free-text question and save it on that question."""
    assessment = _owned_assessment(db, assessment_id, recruiter)
    _require_no_attempts(db, assessment)
    question = db.scalar(
        select(AssessmentQuestion).where(
            AssessmentQuestion.id == question_id, AssessmentQuestion.assessment_id == assessment.id
        )
    )
    if question is None:
        raise HTTPException(404, "Question not found.")
    if question.question_type != QuestionType.free_text:
        raise HTTPException(422, "Multiple-choice questions are scored automatically and need no rubric.")

    if ai is not None:
        used = db.scalar(
            select(func.count()).select_from(ActivityLog).where(
                ActivityLog.actor_id == recruiter.id,
                ActivityLog.action == "rubric_generated_ai",
                ActivityLog.created_at >= datetime.now(timezone.utc) - timedelta(hours=1),
            )
        ) or 0
        if used >= rubrics.MAX_AI_RUBRICS_PER_HOUR:
            raise HTTPException(429, "Hourly AI rubric limit reached. Please try again later.", headers={"Retry-After": "3600"})

    job = db.get(Job, assessment.job_id)
    rubric, source, notice = rubrics.generate_rubric(ai, assessment.kind, job.title, question.prompt, question.max_points)
    question.rubric = [c.model_dump() for c in rubric]
    log_activity(
        db, recruiter.id, "rubric_generated_ai" if source == "claude" else "rubric_generated_template",
        job_id=assessment.job_id, detail={"assessment_id": assessment.id, "question_id": question.id},
    )
    db.commit()
    return RubricOut(
        question_id=question.id, rubric=rubric, source=source, ai_used=source == "claude", notice=notice
    )


# ---------------------------------------------------------------- results and grading


def _attempt_rows(db: Session, attempt: AssessmentAttempt):
    questions = _ordered_questions(db, attempt.assessment_id)
    answers = list(db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt.id)).all())
    return questions, answers


def _attempt_summary(db: Session, attempt: AssessmentAttempt, answers: list[AssessmentAnswer]) -> dict:
    application = db.get(Application, attempt.application_id)
    candidate = db.get(User, application.candidate_id)
    submitted = attempt.status == AttemptStatus.submitted
    return dict(
        attempt_id=attempt.id,
        application_id=attempt.application_id,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        status=attempt.status,
        started_at=attempt.started_at,
        submitted_at=attempt.submitted_at,
        total_score=attempt.total_score if submitted else None,
        max_score=attempt.max_score if submitted else None,
        pending_review=svc.pending_review(answers) if submitted else 0,
    )


def _attempt_result(db: Session, attempt: AssessmentAttempt) -> AttemptResult:
    assessment = db.get(Assessment, attempt.assessment_id)
    questions, answers = _attempt_rows(db, attempt)
    by_question = {a.question_id: a for a in answers}
    items: list[AnswerResult] = []
    for q in questions:
        a = by_question.get(q.id)
        mc = q.question_type == QuestionType.multiple_choice
        items.append(
            AnswerResult(
                answer_id=a.id if a else None,
                question_id=q.id,
                position=q.position,
                prompt=q.prompt,
                question_type=q.question_type,
                options=list(q.options or []),
                correct_option=q.correct_option,
                max_points=q.max_points,
                rubric=[RubricCriterion.model_validate(c) for c in (q.rubric or [])],
                answer_text=a.answer_text if a else None,
                selected_option=a.selected_option if a else None,
                auto_graded=mc,
                score=a.score if a else None,
                reviewer_comment=a.reviewer_comment if a else None,
                needs_review=bool(a and a.score is None),
            )
        )
    return AttemptResult(
        **_attempt_summary(db, attempt, answers),
        assessment_id=assessment.id,
        assessment_title=assessment.title,
        kind=assessment.kind,
        percentage=svc.percentage(attempt, answers),
        answers=items,
    )


def _owned_attempt(db: Session, attempt_id: int, recruiter: User) -> AssessmentAttempt:
    attempt = db.scalar(
        select(AssessmentAttempt)
        .join(Application, AssessmentAttempt.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(AssessmentAttempt.id == attempt_id, Job.recruiter_id == recruiter.id)
    )
    if attempt is None:
        raise HTTPException(404, "Attempt not found.")
    return attempt


@router.get("/assessments/{assessment_id}/attempts", response_model=list[AttemptSummary])
def list_attempts(assessment_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    assessment = _owned_assessment(db, assessment_id, recruiter)
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.assessment_id == assessment.id)
        .order_by(AssessmentAttempt.started_at.desc(), AssessmentAttempt.id.desc())
    ).all()
    out = []
    for attempt in attempts:
        _, answers = _attempt_rows(db, attempt)
        out.append(AttemptSummary(**_attempt_summary(db, attempt, answers)))
    return out


@router.get("/recruiter/applications/{application_id}/assessment-results", response_model=list[AttemptResult])
def application_results(application_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    application = owned_application(db, application_id, recruiter)
    attempts = db.scalars(
        select(AssessmentAttempt)
        .where(AssessmentAttempt.application_id == application.id)
        .order_by(AssessmentAttempt.id)
    ).all()
    return [_attempt_result(db, a) for a in attempts]


@router.get("/assessment-attempts/{attempt_id}", response_model=AttemptResult)
def get_attempt(attempt_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    return _attempt_result(db, _owned_attempt(db, attempt_id, recruiter))


@router.put("/assessment-attempts/{attempt_id}/answers/{answer_id}/grade", response_model=AttemptResult)
def grade_answer(
    attempt_id: int,
    answer_id: int,
    payload: GradeIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    attempt = _owned_attempt(db, attempt_id, recruiter)
    if attempt.status != AttemptStatus.submitted:
        raise HTTPException(409, "This attempt has not been submitted yet.")
    questions, answers = _attempt_rows(db, attempt)
    answer = next((a for a in answers if a.id == answer_id), None)
    if answer is None:
        raise HTTPException(404, "Answer not found.")
    question = next(q for q in questions if q.id == answer.question_id)
    if question.question_type != QuestionType.free_text:
        raise HTTPException(422, "Multiple-choice answers are scored automatically.")
    if not (answer.answer_text or "").strip():
        raise HTTPException(422, "There is no answer to grade.")
    if payload.score > question.max_points:
        raise HTTPException(422, f"The score cannot be more than {question.max_points}.")

    answer.score = round(payload.score, 2)
    answer.reviewer_comment = payload.comment
    svc.recompute_totals(attempt, answers)
    log_activity(
        db, recruiter.id, "assessment_graded",
        job_id=db.get(Application, attempt.application_id).job_id,
        application_id=attempt.application_id,
        detail={"attempt_id": attempt.id, "question_id": question.id},
    )
    db.commit()
    return _attempt_result(db, attempt)
