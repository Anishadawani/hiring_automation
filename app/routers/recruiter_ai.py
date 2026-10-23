"""Recruiter-only AI review and interview questions. Advisory: never changes an application's stage."""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import require_recruiter
from app.models import Application, InterviewQuestion, Job, ScreeningResult, Stage, User
from app.schemas.ai import AIReviewOut, AIStatusOut, InterviewQuestionOut
from app.schemas.applications import ScreeningOut
from app.services import ai_review as air
from app.services.access import owned_application
from app.services.activity import log_activity
from app.services.scoring import score_application

router = APIRouter(prefix="/api/recruiter", tags=["recruiter AI review"])

AI_SOURCES = ("claude", "template")


def get_ai_client() -> air.ClaudeClient | None:
    """None means 'no API key configured': the app runs in rules-only mode and calls no AI."""
    settings = get_settings()
    if not settings.anthropic_api_key:
        return None
    return air.ClaudeClient(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        timeout=settings.ai_timeout_seconds,
    )


@router.get("/ai-status", response_model=AIStatusOut)
def ai_status(_: User = Depends(require_recruiter)):
    settings = get_settings()
    configured = bool(settings.anthropic_api_key)
    return AIStatusOut(
        configured=configured,
        mode="claude" if configured else "rules_only",
        model=settings.anthropic_model if configured else None,
        notice=(
            "AI review is available. It is advisory and a person makes every hiring decision."
            if configured
            else air.NOT_CONFIGURED_NOTICE
        ),
    )


def _enforce_limits(db: Session, recruiter: User, application: Application) -> None:
    """Protect the AI budget from double-clicks and runaway use (only real AI calls count)."""
    now = datetime.now(timezone.utc)
    cooldown = air.MIN_SECONDS_BETWEEN_AI_REVIEWS
    recent = db.scalar(
        select(func.count())
        .select_from(ScreeningResult)
        .where(
            ScreeningResult.application_id == application.id,
            ScreeningResult.ai_model.is_not(None),
            ScreeningResult.created_at >= now - timedelta(seconds=cooldown),
        )
    )
    if recent:
        raise HTTPException(
            429,
            f"An AI review for this application was just run. Wait about {cooldown} seconds.",
            headers={"Retry-After": str(cooldown)},
        )
    hourly = db.scalar(
        select(func.count())
        .select_from(ScreeningResult)
        .join(Application, ScreeningResult.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(
            Job.recruiter_id == recruiter.id,
            ScreeningResult.ai_model.is_not(None),
            ScreeningResult.created_at >= now - timedelta(hours=1),
        )
    )
    if hourly >= air.MAX_AI_REVIEWS_PER_HOUR:
        raise HTTPException(
            429,
            "Hourly AI review limit reached. Please try again later.",
            headers={"Retry-After": "3600"},
        )


@router.post("/applications/{application_id}/ai-review", response_model=AIReviewOut, status_code=201)
def run_ai_review(
    application_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
    ai: air.ClaudeClient | None = Depends(get_ai_client),
):
    application = owned_application(db, application_id, recruiter)
    if application.stage == Stage.withdrawn:
        raise HTTPException(409, "The candidate withdrew this application.")
    job = application.job
    if not job.required_skills:
        raise HTTPException(422, "Add required skills to the job before screening.")
    profile = application.candidate.profile
    resume_text = (profile.resume_text if profile else None) or ""
    declared = list(profile.skills) if profile and profile.skills else []
    if not resume_text and not declared:
        raise HTTPException(422, "This candidate has no resume text or declared skills to review.")
    if ai is not None:
        _enforce_limits(db, recruiter, application)

    # The score is always the deterministic, documented rules score.
    rules = score_application(
        required_skills=list(job.required_skills),
        preferred_skills=list(job.preferred_skills or []),
        min_years_experience=job.min_years_experience,
        resume_text=resume_text,
        profile_skills=declared,
        experience=list(profile.experience) if profile and profile.experience else [],
    )

    review: air.ReviewResult | None = None
    warnings: list[str] = []
    ai_error: str | None = None
    ai_model: str | None = None

    if ai is None:
        ai_error = air.NOT_CONFIGURED_NOTICE
    elif not resume_text:
        ai_error = "There is no resume text for the AI to review, so this is the rules-based result only."
    else:
        try:
            sent = air.prepare_resume_for_ai(resume_text)
            reply = ai.complete(
                air.SYSTEM_PROMPT,
                air.build_user_prompt(
                    title=job.title,
                    description=job.description,
                    required=list(job.required_skills),
                    preferred=list(job.preferred_skills or []),
                    matched=rules.matched_skills,
                    missing=rules.missing_skills,
                    resume_for_ai=sent,
                ),
            )
            review, warnings = air.validate_review(
                reply.text, sent, list(job.required_skills), list(job.preferred_skills or [])
            )
            ai_model = reply.model
        except (air.AIUnavailable, air.AIInvalid) as exc:
            ai_error = f"{exc} Showing the rules-based result only."
            review = None

    ai_used = review is not None
    breakdown = dict(rules.breakdown)
    if review is not None:
        breakdown["ai_review"] = {
            "strengths": review.strengths,
            "gaps": review.gaps,
            "warnings": warnings,
        }

    screening = ScreeningResult(
        application_id=application.id,
        mode="claude" if ai_used else "rules",
        match_score=rules.score,
        score_breakdown=breakdown,
        matched_skills=rules.matched_skills,
        missing_skills=rules.missing_skills,
        evidence=rules.evidence,
        ai_summary=review.summary if review else None,
        ai_model=ai_model if ai_used else None,
        ai_error=ai_error,
    )
    db.add(screening)

    if review is not None and review.questions:
        question_rows = [{**q, "source": "claude"} for q in review.questions]
    else:
        if review is not None:
            warnings.append("The AI produced no verifiable questions, so template questions are shown.")
        question_rows = [
            {**q, "source": "template"}
            for q in air.template_questions(rules.evidence, rules.missing_skills)
        ]

    # Replace the previous suggestions for this application with the new batch.
    db.execute(
        delete(InterviewQuestion).where(
            InterviewQuestion.application_id == application.id,
            InterviewQuestion.source.in_(AI_SOURCES),
        )
    )
    for q in question_rows:
        db.add(
            InterviewQuestion(
                application_id=application.id,
                question=q["question"],
                rationale=q.get("rationale") or "",
                evidence=q.get("evidence"),
                source=q["source"],
            )
        )
    log_activity(
        db,
        recruiter.id,
        "ai_review_run",
        job_id=job.id,
        application_id=application.id,
        detail={"ai_used": ai_used, "questions": len(question_rows)},
    )
    db.commit()
    db.refresh(screening)

    stored = db.scalars(
        select(InterviewQuestion)
        .where(InterviewQuestion.application_id == application.id)
        .order_by(InterviewQuestion.id)
    ).all()
    ai_part = breakdown.get("ai_review", {})
    return AIReviewOut(
        **ScreeningOut.model_validate(screening).model_dump(),
        ai_used=ai_used,
        demo_mode=ai is None,
        strengths=ai_part.get("strengths", []),
        gaps=ai_part.get("gaps", []),
        warnings=warnings,
        questions=[InterviewQuestionOut.model_validate(q) for q in stored],
    )


@router.get("/applications/{application_id}/interview-questions", response_model=list[InterviewQuestionOut])
def list_interview_questions(
    application_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    application = owned_application(db, application_id, recruiter)
    return db.scalars(
        select(InterviewQuestion)
        .where(InterviewQuestion.application_id == application.id)
        .order_by(InterviewQuestion.id)
    ).all()