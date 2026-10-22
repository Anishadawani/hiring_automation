"""Candidate applications: apply, track status, withdraw."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_candidate
from app.models import Application, Job, JobStatus, Stage, User
from app.schemas.applications import ApplyRequest, CandidateApplicationOut
from app.services.activity import log_activity

router = APIRouter(prefix="/api/applications", tags=["applications (candidate)"])

FINAL_STAGES = {Stage.hired, Stage.rejected, Stage.withdrawn}


def _out(app: Application) -> CandidateApplicationOut:
    return CandidateApplicationOut(
        id=app.id,
        job_id=app.job_id,
        job_title=app.job.title,
        stage=app.stage,
        cover_letter=app.cover_letter,
        created_at=app.created_at,
        updated_at=app.updated_at,
    )


def _own_application(db: Session, application_id: int, user: User) -> Application:
    app = db.scalar(
        select(Application).where(Application.id == application_id, Application.candidate_id == user.id)
    )
    if app is None:
        raise HTTPException(404, "Application not found.")
    return app


@router.post("", response_model=CandidateApplicationOut, status_code=201)
def apply(payload: ApplyRequest, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    job = db.scalar(select(Job).where(Job.id == payload.job_id, Job.status == JobStatus.open))
    if job is None:
        raise HTTPException(404, "This job is not open for applications.")
    profile = user.profile
    if profile is None or not profile.resume_text:
        raise HTTPException(400, "Upload your resume before applying.")
    if db.scalar(
        select(Application.id).where(Application.job_id == job.id, Application.candidate_id == user.id)
    ):
        raise HTTPException(409, "You have already applied to this job.")

    application = Application(job_id=job.id, candidate_id=user.id, cover_letter=payload.cover_letter)
    try:
        db.add(application)
        db.flush()
        log_activity(db, user.id, "application_submitted", job_id=job.id, application_id=application.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "You have already applied to this job.")
    db.refresh(application)
    return _out(application)


# "/mine" must be declared before "/{application_id}" so it is not parsed as an id.
@router.get("/mine", response_model=list[CandidateApplicationOut])
def my_applications(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    apps = db.scalars(
        select(Application)
        .where(Application.candidate_id == user.id)
        .order_by(Application.created_at.desc(), Application.id.desc())
    ).all()
    return [_out(a) for a in apps]


@router.get("/{application_id}", response_model=CandidateApplicationOut)
def get_application(
    application_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)
):
    return _out(_own_application(db, application_id, user))


@router.post("/{application_id}/withdraw", response_model=CandidateApplicationOut)
def withdraw(application_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    application = _own_application(db, application_id, user)
    if application.stage in FINAL_STAGES:
        raise HTTPException(409, "This application can no longer be withdrawn.")
    application.stage = Stage.withdrawn
    log_activity(
        db, user.id, "application_withdrawn", job_id=application.job_id, application_id=application.id
    )
    db.commit()
    db.refresh(application)
    return _out(application)