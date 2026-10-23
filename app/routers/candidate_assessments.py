"""Candidate side of assessments: see tasks, start, autosave answers, submit.

A candidate can only act on their own applications, and only while a recruiter has moved the
application to the 'assessment' stage. Candidates never see scores, correct answers or rubrics.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_candidate
from app.models import (
    Application,
    Assessment,
    AssessmentAnswer,
    AssessmentAttempt,
    AssessmentQuestion,
    AttemptStatus,
    Job,
    QuestionType,
    Stage,
    User,
)
from app.schemas.assessments import (
    AnswerIn,
    AttemptOut,
    CandidateQuestionOut,
    CandidateTaskOut,
    SavedAnswer,
)
from app.services import assessments as svc
from app.services.activity import log_activity

router = APIRouter(prefix="/api/candidate", tags=["assessments (candidate)"])


def _questions(db: Session, assessment_id: int) -> list[AssessmentQuestion]:
    return list(
        db.scalars(
            select(AssessmentQuestion)
            .where(AssessmentQuestion.assessment_id == assessment_id)
            .order_by(AssessmentQuestion.position, AssessmentQuestion.id)
        ).all()
    )


def _answers(db: Session, attempt_id: int) -> list[AssessmentAnswer]:
    return list(db.scalars(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id)).all())


def _is_answered(a: AssessmentAnswer) -> bool:
    return a.selected_option is not None or bool((a.answer_text or "").strip())


def _out(db: Session, attempt: AssessmentAttempt, assessment: Assessment, questions: list[AssessmentQuestion]) -> AttemptOut:
    answers = _answers(db, attempt.id)
    in_progress = attempt.status == AttemptStatus.in_progress
    return AttemptOut(
        attempt_id=attempt.id,
        assessment_id=assessment.id,
        application_id=attempt.application_id,
        title=assessment.title,
        kind=assessment.kind,
        instructions=assessment.instructions or "",
        time_limit_minutes=assessment.time_limit_minutes,
        status=attempt.status,
        started_at=attempt.started_at,
        deadline=svc.deadline_for(attempt, assessment),
        seconds_remaining=svc.seconds_remaining(attempt, assessment) if in_progress else None,
        total_questions=len(questions),
        answered_count=sum(1 for a in answers if _is_answered(a)),
        questions=[
            CandidateQuestionOut(
                id=q.id, position=q.position, prompt=q.prompt, question_type=q.question_type,
                options=list(q.options or []), max_points=q.max_points,
            )
            for q in questions
        ],
        answers=[
            SavedAnswer(question_id=a.question_id, answer_text=a.answer_text, selected_option=a.selected_option)
            for a in answers
            if _is_answered(a)
        ],
    )


def _own_application(db: Session, application_id: int, user: User) -> Application:
    application = db.scalar(
        select(Application).where(Application.id == application_id, Application.candidate_id == user.id)
    )
    if application is None:
        raise HTTPException(404, "Application not found.")
    return application


def _resolve(db: Session, attempt_id: int, user: User):
    """Load an attempt the candidate owns. If its time ran out, close it first."""
    row = db.execute(
        select(AssessmentAttempt, Assessment, Application)
        .join(Assessment, AssessmentAttempt.assessment_id == Assessment.id)
        .join(Application, AssessmentAttempt.application_id == Application.id)
        .where(AssessmentAttempt.id == attempt_id, Application.candidate_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(404, "Attempt not found.")
    attempt, assessment, application = row
    questions = _questions(db, assessment.id)
    if svc.is_expired(attempt, assessment):
        svc.finalize_attempt(db, attempt, questions, _answers(db, attempt.id), svc.deadline_for(attempt, assessment))
        log_activity(
            db, user.id, "assessment_time_expired", job_id=application.job_id,
            application_id=application.id, detail={"attempt_id": attempt.id},
        )
        db.commit()
    return attempt, assessment, application, questions


def _require_open(attempt: AssessmentAttempt, application: Application) -> None:
    if attempt.status != AttemptStatus.in_progress:
        raise HTTPException(409, "This assessment has been submitted (or time ran out). Your answers are final.")
    if application.stage != Stage.assessment:
        raise HTTPException(409, "This assessment is no longer open.")


@router.get("/assessments", response_model=list[CandidateTaskOut])
def my_assessments(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Application, Job.title).join(Job, Application.job_id == Job.id).where(Application.candidate_id == user.id)
    ).all()
    if not rows:
        return []
    app_ids = [a.id for a, _ in rows]
    job_ids = {a.job_id for a, _ in rows}
    assessments = db.scalars(
        select(Assessment).where(Assessment.job_id.in_(job_ids), Assessment.is_published.is_(True)).order_by(Assessment.id)
    ).all()
    counts = dict(
        db.execute(
            select(AssessmentQuestion.assessment_id, func.count())
            .where(AssessmentQuestion.assessment_id.in_([a.id for a in assessments] or [0]))
            .group_by(AssessmentQuestion.assessment_id)
        ).all()
    )
    attempts = {
        (t.assessment_id, t.application_id): t
        for t in db.scalars(select(AssessmentAttempt).where(AssessmentAttempt.application_id.in_(app_ids))).all()
    }
    by_id = {a.id: a for a in assessments}
    tasks: list[CandidateTaskOut] = []
    for application, job_title in rows:
        for assessment in assessments:
            if assessment.job_id != application.job_id:
                continue
            attempt = attempts.get((assessment.id, application.id))
            if application.stage != Stage.assessment and attempt is None:
                continue
            if attempt is None:
                status = "not_started"
            elif attempt.status == AttemptStatus.submitted or svc.is_expired(attempt, by_id[assessment.id]):
                status = "submitted"
            else:
                status = "in_progress"
            tasks.append(
                CandidateTaskOut(
                    application_id=application.id,
                    job_title=job_title,
                    assessment_id=assessment.id,
                    title=assessment.title,
                    kind=assessment.kind,
                    time_limit_minutes=assessment.time_limit_minutes,
                    question_count=counts.get(assessment.id, 0),
                    status=status,
                    attempt_id=attempt.id if attempt else None,
                )
            )
    return tasks


@router.post("/applications/{application_id}/assessments/{assessment_id}/start", response_model=AttemptOut)
def start_assessment(
    application_id: int,
    assessment_id: int,
    response: Response,
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    application = _own_application(db, application_id, user)
    assessment = db.scalar(
        select(Assessment).where(
            Assessment.id == assessment_id, Assessment.job_id == application.job_id, Assessment.is_published.is_(True)
        )
    )
    if assessment is None:
        raise HTTPException(404, "Assessment not found.")

    existing = db.scalar(
        select(AssessmentAttempt).where(
            AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.application_id == application.id
        )
    )
    if existing is not None:  # starting again simply resumes (or shows the submitted attempt)
        attempt, assessment, application, questions = _resolve(db, existing.id, user)
        if attempt.status == AttemptStatus.in_progress and application.stage != Stage.assessment:
            raise HTTPException(409, "This assessment is no longer open.")
        return _out(db, attempt, assessment, questions)

    if application.stage != Stage.assessment:
        raise HTTPException(409, "This assessment is not open for you right now.")
    questions = _questions(db, assessment.id)
    if not questions:
        raise HTTPException(409, "This assessment has no questions yet.")
    attempt = AssessmentAttempt(assessment_id=assessment.id, application_id=application.id)
    try:
        db.add(attempt)
        db.flush()
        log_activity(
            db, user.id, "assessment_started", job_id=application.job_id,
            application_id=application.id, detail={"assessment_id": assessment.id},
        )
        db.commit()
    except IntegrityError:  # double-click race: someone else created it first
        db.rollback()
        existing = db.scalar(
            select(AssessmentAttempt).where(
                AssessmentAttempt.assessment_id == assessment.id, AssessmentAttempt.application_id == application.id
            )
        )
        return _out(db, existing, assessment, questions)
    db.refresh(attempt)
    response.status_code = 201
    return _out(db, attempt, assessment, questions)


@router.get("/attempts/{attempt_id}", response_model=AttemptOut)
def get_attempt(attempt_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    attempt, assessment, _, questions = _resolve(db, attempt_id, user)
    return _out(db, attempt, assessment, questions)


@router.put("/attempts/{attempt_id}/answers/{question_id}", response_model=SavedAnswer)
def save_answer(
    attempt_id: int,
    question_id: int,
    payload: AnswerIn,
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    attempt, assessment, application, questions = _resolve(db, attempt_id, user)
    _require_open(attempt, application)
    question = next((q for q in questions if q.id == question_id), None)
    if question is None:
        raise HTTPException(404, "Question not found.")

    if question.question_type == QuestionType.multiple_choice:
        if payload.answer_text is not None:
            raise HTTPException(422, "Multiple-choice questions are answered with selected_option.")
        if payload.selected_option is not None and not 0 <= payload.selected_option < len(question.options or []):
            raise HTTPException(422, "That option does not exist.")
    elif payload.selected_option is not None:
        raise HTTPException(422, "Free-text questions are answered with answer_text.")

    answer = db.scalar(
        select(AssessmentAnswer).where(
            AssessmentAnswer.attempt_id == attempt.id, AssessmentAnswer.question_id == question.id
        )
    )
    if answer is None:
        answer = AssessmentAnswer(attempt_id=attempt.id, question_id=question.id)
        db.add(answer)
    answer.answer_text = payload.answer_text
    answer.selected_option = payload.selected_option
    db.commit()
    return SavedAnswer(question_id=question.id, answer_text=answer.answer_text, selected_option=answer.selected_option)


@router.post("/attempts/{attempt_id}/submit", response_model=AttemptOut)
def submit_attempt(attempt_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    attempt, assessment, application, questions = _resolve(db, attempt_id, user)
    if attempt.status == AttemptStatus.submitted:
        return _out(db, attempt, assessment, questions)  # submitting twice is harmless
    _require_open(attempt, application)
    svc.finalize_attempt(db, attempt, questions, _answers(db, attempt.id), datetime.now(timezone.utc))
    log_activity(
        db, user.id, "assessment_submitted", job_id=application.job_id,
        application_id=application.id, detail={"attempt_id": attempt.id},
    )
    db.commit()
    db.refresh(attempt)
    return _out(db, attempt, assessment, questions)
