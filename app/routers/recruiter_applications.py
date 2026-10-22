"""Recruiter pipeline: view applicants, move stages, add notes, run screening."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_recruiter
from app.models import (
    Application,
    Job,
    RecruiterNote,
    ScreeningResult,
    Stage,
    User,
    utcnow,
)
from app.schemas.applications import (
    ApplicationDetail,
    ApplicationSummary,
    NoteCreate,
    NoteOut,
    ScreeningOut,
    StageUpdate,
)
from app.schemas.common import Page
from app.schemas.profile import ProfileOut
from app.services.activity import log_activity
from app.services.query import contains_pattern
from app.services.resume import ResumeError, resolve_resume_path
from app.services.scoring import METHODOLOGY, score_application

router = APIRouter(prefix="/api/recruiter", tags=["recruiter pipeline"])

# Stages that represent a recorded human decision.
DECISION_STAGES = {Stage.shortlisted, Stage.offer, Stage.hired, Stage.rejected}


def _owned_application(db: Session, application_id: int, recruiter: User) -> Application:
    # 404 (not 403) for other recruiters' applications so their existence is not revealed.
    application = db.scalar(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .where(Application.id == application_id, Job.recruiter_id == recruiter.id)
    )
    if application is None:
        raise HTTPException(404, "Application not found.")
    return application


def _detail(db: Session, application: Application) -> ApplicationDetail:
    candidate = application.candidate
    profile = candidate.profile
    decided_by = db.get(User, application.decided_by_id) if application.decided_by_id else None
    screenings = sorted(application.screenings, key=lambda s: (s.created_at, s.id), reverse=True)
    notes = sorted(application.notes, key=lambda n: (n.created_at, n.id), reverse=True)
    latest = screenings[0] if screenings else None
    return ApplicationDetail(
        id=application.id,
        job_id=application.job_id,
        job_title=application.job.title,
        candidate_id=candidate.id,
        candidate_name=candidate.full_name,
        candidate_email=candidate.email,
        stage=application.stage,
        created_at=application.created_at,
        updated_at=application.updated_at,
        latest_score=latest.match_score if latest else None,
        latest_screening_mode=latest.mode if latest else None,
        cover_letter=application.cover_letter,
        decision_reason=application.decision_reason,
        decided_by_name=decided_by.full_name if decided_by else None,
        decided_at=application.decided_at,
        has_resume=bool(profile and profile.resume_path),
        profile=ProfileOut.model_validate(profile) if profile else None,
        notes=[
            NoteOut(id=n.id, author_name=n.author.full_name, body=n.body, created_at=n.created_at)
            for n in notes
        ],
        screenings=[ScreeningOut.model_validate(s) for s in screenings],
    )


@router.get("/scoring-method")
def scoring_method(_: User = Depends(require_recruiter)):
    """The documented formula behind the rules-based match score."""
    return METHODOLOGY


@router.get("/applications", response_model=Page[ApplicationSummary])
def list_applications(
    job_id: int | None = None,
    stage: Stage | None = None,
    q: str | None = Query(default=None, max_length=100),
    min_score: float | None = Query(default=None, ge=0, le=100),
    sort: Literal["newest", "score"] = "newest",
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    latest_id = (
        select(func.max(ScreeningResult.id))
        .where(ScreeningResult.application_id == Application.id)
        .correlate(Application)
        .scalar_subquery()
    )
    latest_score = (
        select(ScreeningResult.match_score).where(ScreeningResult.id == latest_id).scalar_subquery()
    ).label("latest_score")
    latest_mode = (
        select(ScreeningResult.mode).where(ScreeningResult.id == latest_id).scalar_subquery()
    ).label("latest_mode")

    filters = [Job.recruiter_id == recruiter.id]
    if job_id is not None:
        filters.append(Application.job_id == job_id)
    if stage is not None:
        filters.append(Application.stage == stage)
    if q and q.strip():
        pattern = contains_pattern(q)
        filters.append(or_(User.full_name.ilike(pattern, escape="\\"), User.email.ilike(pattern, escape="\\")))
    if min_score is not None:
        filters.append(latest_score >= min_score)

    joined = (
        select(Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.candidate_id == User.id)
        .where(*filters)
    )
    total = db.scalar(select(func.count()).select_from(joined.subquery())) or 0

    order = (
        [latest_score.desc().nulls_last(), Application.id.desc()]
        if sort == "score"
        else [Application.created_at.desc(), Application.id.desc()]
    )
    rows = db.execute(
        select(Application, Job.title, User.full_name, User.email, latest_score, latest_mode)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.candidate_id == User.id)
        .where(*filters)
        .order_by(*order)
        .limit(limit)
        .offset(offset)
    ).all()
    items = [
        ApplicationSummary(
            id=a.id,
            job_id=a.job_id,
            job_title=title,
            candidate_id=a.candidate_id,
            candidate_name=name,
            candidate_email=email,
            stage=a.stage,
            created_at=a.created_at,
            updated_at=a.updated_at,
            latest_score=score,
            latest_screening_mode=mode,
        )
        for a, title, name, email, score, mode in rows
    ]
    return Page[ApplicationSummary](items=items, total=total)


@router.get("/applications/{application_id}", response_model=ApplicationDetail)
def get_application(
    application_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    return _detail(db, _owned_application(db, application_id, recruiter))


@router.patch("/applications/{application_id}/stage", response_model=ApplicationDetail)
def change_stage(
    application_id: int,
    payload: StageUpdate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, recruiter)
    if application.stage == Stage.withdrawn:
        raise HTTPException(409, "The candidate withdrew this application; it cannot be changed.")
    if payload.stage == application.stage:
        return _detail(db, application)

    previous = application.stage
    application.stage = payload.stage
    if payload.stage in DECISION_STAGES:
        application.decision_reason = payload.reason
        application.decided_by_id = recruiter.id
        application.decided_at = utcnow()
    else:
        application.decision_reason = None
        application.decided_by_id = None
        application.decided_at = None
    log_activity(
        db, recruiter.id, "stage_changed",
        job_id=application.job_id, application_id=application.id,
        detail={"from": previous.value, "to": payload.stage.value},
    )
    db.commit()
    db.refresh(application)
    return _detail(db, application)


@router.post("/applications/{application_id}/notes", response_model=NoteOut, status_code=201)
def add_note(
    application_id: int,
    payload: NoteCreate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    application = _owned_application(db, application_id, recruiter)
    note = RecruiterNote(application_id=application.id, author_id=recruiter.id, body=payload.body)
    db.add(note)
    log_activity(db, recruiter.id, "note_added", job_id=application.job_id, application_id=application.id)
    db.commit()
    db.refresh(note)
    return NoteOut(id=note.id, author_name=recruiter.full_name, body=note.body, created_at=note.created_at)


@router.post("/applications/{application_id}/screen", response_model=ScreeningOut, status_code=201)
def run_rules_screening(
    application_id: int,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    """Explainable rules-based screening. Advisory only: never changes the stage."""
    application = _owned_application(db, application_id, recruiter)
    if application.stage == Stage.withdrawn:
        raise HTTPException(409, "The candidate withdrew this application.")
    job = application.job
    if not job.required_skills:
        raise HTTPException(422, "Add required skills to the job before screening.")
    profile = application.candidate.profile
    resume_text = (profile.resume_text if profile else None) or ""
    declared = list(profile.skills) if profile and profile.skills else []
    if not resume_text and not declared:
        raise HTTPException(422, "This candidate has no resume text or declared skills to screen.")

    result = score_application(
        required_skills=list(job.required_skills),
        preferred_skills=list(job.preferred_skills or []),
        min_years_experience=job.min_years_experience,
        resume_text=resume_text,
        profile_skills=declared,
        experience=list(profile.experience) if profile and profile.experience else [],
    )
    screening = ScreeningResult(
        application_id=application.id,
        mode="rules",
        match_score=result.score,
        score_breakdown=result.breakdown,
        matched_skills=result.matched_skills,
        missing_skills=result.missing_skills,
        evidence=result.evidence,
    )
    db.add(screening)
    log_activity(
        db, recruiter.id, "screening_run", job_id=job.id, application_id=application.id,
        detail={"mode": "rules"},
    )
    db.commit()
    db.refresh(screening)
    return ScreeningOut.model_validate(screening)


@router.get("/applications/{application_id}/resume")
def download_resume(
    application_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    application = _owned_application(db, application_id, recruiter)
    profile = application.candidate.profile
    if profile is None or not profile.resume_path:
        raise HTTPException(404, "No resume on file.")
    try:
        path = resolve_resume_path(profile.resume_path)
    except ResumeError:
        raise HTTPException(404, "No resume on file.")
    if not path.is_file():
        raise HTTPException(404, "No resume on file.")
    media_type = "application/pdf" if path.suffix == ".pdf" else "text/plain"
    return FileResponse(
        path,
        media_type=media_type,
        filename=profile.resume_filename or "resume",
        headers={"X-Content-Type-Options": "nosniff"},
    )