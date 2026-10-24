"""Interview scheduling (recruiter), invitations and consent (candidate).

Scheduling never changes an application's stage and never contacts the candidate by itself:
a recruiter decides and the candidate sees the invitation in their account.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_candidate, require_recruiter
from app.models import Application, Interview, InterviewStatus, Job, Stage, User
from app.schemas.interviews import (
    CandidateInterviewOut,
    ConsentIn,
    ConsentNoticeOut,
    InterviewIn,
    InterviewOut,
    InterviewUpdate,
    RecruiterInterviewRow,
    RespondIn,
)
from app.services import interviews as svc
from app.services.access import owned_application
from app.services.activity import log_activity
from app.services.assessments import aware

router = APIRouter(prefix="/api", tags=["interviews"])

CLOSED_STAGES = {Stage.withdrawn, Stage.rejected, Stage.hired}


def _out(db: Session, interview: Interview, candidate_id: int) -> InterviewOut:
    return InterviewOut(
        id=interview.id,
        application_id=interview.application_id,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        mode=interview.mode,
        location=interview.location,
        notes=interview.notes,
        status=interview.status,
        join_method=svc.join_method(interview.mode, interview.location),
        candidate_response=svc.attendance_response(db, interview.id, candidate_id),
        live_av_consent=svc.live_av_consent(db, interview.id, candidate_id),
        created_at=interview.created_at,
    )


def _owned_interview(db: Session, interview_id: int, recruiter: User) -> tuple[Interview, Application]:
    row = db.execute(
        select(Interview, Application)
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(Interview.id == interview_id, Job.recruiter_id == recruiter.id)
    ).first()
    if row is None:
        raise HTTPException(404, "Interview not found.")
    return row[0], row[1]


def _check_conflicts(
    db: Session, recruiter: User, start: datetime, minutes: int, ignore_id: int | None = None
) -> None:
    """A recruiter cannot be in two interviews at once."""
    window_start, window_end = start - timedelta(days=1), start + timedelta(days=1)
    existing = db.scalars(
        select(Interview)
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(
            Job.recruiter_id == recruiter.id,
            Interview.status == InterviewStatus.scheduled,
            Interview.scheduled_at >= window_start,
            Interview.scheduled_at <= window_end,
        )
    ).all()
    for other in existing:
        if other.id != ignore_id and svc.overlaps(start, minutes, other.scheduled_at, other.duration_minutes):
            raise HTTPException(409, "You already have an interview that overlaps with this time.")


# ----------------------------------------------------------------------- recruiter


@router.post("/recruiter/applications/{application_id}/interviews", response_model=InterviewOut, status_code=201)
def schedule_interview(
    application_id: int,
    payload: InterviewIn,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    application = owned_application(db, application_id, recruiter)
    if application.stage in CLOSED_STAGES:
        raise HTTPException(409, "This application is closed, so an interview cannot be scheduled.")
    _check_conflicts(db, recruiter, payload.scheduled_at, payload.duration_minutes)
    interview = Interview(
        application_id=application.id,
        scheduled_at=payload.scheduled_at,
        duration_minutes=payload.duration_minutes,
        mode=payload.mode,
        location=payload.location,
        notes=payload.notes,
        status=InterviewStatus.scheduled,
        created_by_id=recruiter.id,
    )
    db.add(interview)
    db.flush()
    log_activity(
        db, recruiter.id, "interview_scheduled", job_id=application.job_id, application_id=application.id,
        detail={"interview_id": interview.id, "mode": interview.mode},
    )
    db.commit()
    db.refresh(interview)
    return _out(db, interview, application.candidate_id)


@router.get("/recruiter/applications/{application_id}/interviews", response_model=list[InterviewOut])
def application_interviews(
    application_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)
):
    application = owned_application(db, application_id, recruiter)
    rows = db.scalars(
        select(Interview).where(Interview.application_id == application.id).order_by(Interview.scheduled_at, Interview.id)
    ).all()
    return [_out(db, i, application.candidate_id) for i in rows]


@router.get("/recruiter/interviews", response_model=list[RecruiterInterviewRow])
def my_interviews(
    status: InterviewStatus | None = InterviewStatus.scheduled,
    upcoming_only: bool = Query(default=True),
    limit: int = Query(default=50, ge=1, le=100),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    stmt = (
        select(Interview, Application, User.full_name, Job.title)
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .join(User, Application.candidate_id == User.id)
        .where(Job.recruiter_id == recruiter.id)
    )
    if status is not None:
        stmt = stmt.where(Interview.status == status)
    if upcoming_only:
        stmt = stmt.where(Interview.scheduled_at >= datetime.now(timezone.utc) - timedelta(hours=4))
    rows = db.execute(stmt.order_by(Interview.scheduled_at, Interview.id).limit(limit)).all()
    return [
        RecruiterInterviewRow(**_out(db, i, a.candidate_id).model_dump(), candidate_name=name, job_title=title)
        for i, a, name, title in rows
    ]


@router.patch("/recruiter/interviews/{interview_id}", response_model=InterviewOut)
def update_interview(
    interview_id: int,
    payload: InterviewUpdate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    interview, application = _owned_interview(db, interview_id, recruiter)
    if not svc.is_open(interview):
        raise HTTPException(409, f"This interview is already {interview.status.value} and cannot be changed.")
    data = payload.model_dump(exclude_unset=True)

    new_start = data.get("scheduled_at", interview.scheduled_at)
    new_minutes = data.get("duration_minutes", interview.duration_minutes)
    new_mode = data.get("mode", interview.mode)
    new_location = (data.get("location", interview.location) or "").strip() or None
    if new_mode in ("phone", "onsite") and not new_location:
        raise HTTPException(422, "Add the phone number or address for this interview.")

    time_changed = "scheduled_at" in data or "duration_minutes" in data
    closing = data.get("status")
    if time_changed and closing is None:
        _check_conflicts(db, recruiter, new_start, new_minutes, ignore_id=interview.id)

    for field in ("scheduled_at", "duration_minutes", "mode", "notes"):
        if field in data:
            setattr(interview, field, data[field])
    if "location" in data or "mode" in data:
        interview.location = new_location
    if time_changed or "mode" in data or "location" in data:
        # The candidate agreed to something different: ask again.
        svc.clear_choice(db, interview.id, application.candidate_id, "attendance")
    if closing is not None:
        interview.status = closing
    action = {InterviewStatus.cancelled: "interview_cancelled", InterviewStatus.completed: "interview_completed"}.get(
        closing, "interview_updated"
    )
    log_activity(
        db, recruiter.id, action, job_id=application.job_id, application_id=application.id,
        detail={"interview_id": interview.id},
    )
    db.commit()
    db.refresh(interview)
    return _out(db, interview, application.candidate_id)


# ----------------------------------------------------------------------- candidate


@router.get("/interviews/consent-notice", response_model=ConsentNoticeOut)
def consent_notice(_: User = Depends(get_current_user)):
    """The exact wording a candidate is shown before agreeing to use camera and microphone."""
    return ConsentNoticeOut(**svc.CONSENT_NOTICE)


def _candidate_interview(db: Session, interview_id: int, user: User) -> tuple[Interview, Application]:
    row = db.execute(
        select(Interview, Application)
        .join(Application, Interview.application_id == Application.id)
        .where(Interview.id == interview_id, Application.candidate_id == user.id)
    ).first()
    if row is None:
        raise HTTPException(404, "Interview not found.")
    return row[0], row[1]


def _candidate_view(db: Session, interview: Interview, job_title: str, user: User) -> CandidateInterviewOut:
    now = datetime.now(timezone.utc)
    end = aware(interview.scheduled_at) + timedelta(minutes=interview.duration_minutes)
    return CandidateInterviewOut(
        id=interview.id,
        application_id=interview.application_id,
        job_title=job_title,
        scheduled_at=interview.scheduled_at,
        duration_minutes=interview.duration_minutes,
        mode=interview.mode,
        location=interview.location,
        status=interview.status,
        join_method=svc.join_method(interview.mode, interview.location),
        my_response=svc.attendance_response(db, interview.id, user.id),
        live_av_consent=svc.live_av_consent(db, interview.id, user.id),
        upcoming=interview.status == InterviewStatus.scheduled and end > now,
    )


@router.get("/candidate/interviews", response_model=list[CandidateInterviewOut])
def my_invitations(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    rows = db.execute(
        select(Interview, Job.title)
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(Application.candidate_id == user.id)
        .order_by(Interview.scheduled_at, Interview.id)
    ).all()
    return [_candidate_view(db, i, title, user) for i, title in rows]


@router.post("/candidate/interviews/{interview_id}/respond", response_model=CandidateInterviewOut)
def respond(
    interview_id: int, payload: RespondIn, user: User = Depends(require_candidate), db: Session = Depends(get_db)
):
    interview, application = _candidate_interview(db, interview_id, user)
    if not svc.is_open(interview):
        raise HTTPException(409, "This interview is no longer open for a response.")
    granted = payload.response == "confirmed"
    svc.set_choice(db, interview.id, user.id, "attendance", granted, None)
    log_activity(
        db, user.id, "interview_response", job_id=application.job_id, application_id=application.id,
        detail={"interview_id": interview.id, "response": payload.response},
    )
    db.commit()
    return _candidate_view(db, interview, application.job.title, user)


@router.put("/candidate/interviews/{interview_id}/consent", response_model=CandidateInterviewOut)
def set_consent(
    interview_id: int, payload: ConsentIn, user: User = Depends(require_candidate), db: Session = Depends(get_db)
):
    """Record yes or no for live camera/microphone. Saying no never affects the application."""
    interview, application = _candidate_interview(db, interview_id, user)
    if not svc.is_open(interview):
        raise HTTPException(409, "This interview is no longer open.")
    svc.set_choice(db, interview.id, user.id, payload.kind, payload.granted, svc.NOTICE_VERSION)
    log_activity(
        db, user.id, "interview_consent", job_id=application.job_id, application_id=application.id,
        detail={"interview_id": interview.id, "kind": payload.kind, "granted": payload.granted,
                "notice_version": svc.NOTICE_VERSION},
    )
    db.commit()
    return _candidate_view(db, interview, application.job.title, user)
