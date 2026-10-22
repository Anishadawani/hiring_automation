"""Recruiter job management. A recruiter can only see and change their own jobs."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_recruiter
from app.models import Application, Job, JobStatus, User
from app.schemas.common import Page
from app.schemas.jobs import JobCreate, JobOut, JobStatusUpdate, JobUpdate
from app.services.activity import log_activity
from app.services.query import contains_pattern

router = APIRouter(prefix="/api/jobs", tags=["jobs (recruiter)"])


def _owned_job(db: Session, job_id: int, recruiter: User) -> Job:
    job = db.scalar(select(Job).where(Job.id == job_id, Job.recruiter_id == recruiter.id))
    if job is None:
        raise HTTPException(404, "Job not found.")
    return job


def _out(db: Session, jobs: list[Job]) -> list[JobOut]:
    counts: dict[int, int] = {}
    if jobs:
        rows = db.execute(
            select(Application.job_id, func.count())
            .where(Application.job_id.in_([j.id for j in jobs]))
            .group_by(Application.job_id)
        ).all()
        counts = {job_id: n for job_id, n in rows}
    return [
        JobOut.model_validate(j).model_copy(update={"application_count": counts.get(j.id, 0)})
        for j in jobs
    ]


@router.get("", response_model=Page[JobOut])
def list_jobs(
    status: JobStatus | None = None,
    q: str | None = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    filters = [Job.recruiter_id == recruiter.id]
    if status:
        filters.append(Job.status == status)
    if q and q.strip():
        filters.append(Job.title.ilike(contains_pattern(q), escape="\\"))
    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    jobs = db.scalars(
        select(Job).where(*filters).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)
    ).all()
    return Page[JobOut](items=_out(db, list(jobs)), total=total)


@router.post("", response_model=JobOut, status_code=201)
def create_job(
    payload: JobCreate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    if payload.status == JobStatus.open and not payload.required_skills:
        raise HTTPException(422, "Add at least one required skill before publishing a job.")
    data = payload.model_dump(exclude={"status"})
    job = Job(recruiter_id=recruiter.id, status=payload.status, **data)
    db.add(job)
    db.flush()
    log_activity(db, recruiter.id, "job_created", job_id=job.id, detail={"title": job.title})
    db.commit()
    return _out(db, [job])[0]


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    return _out(db, [_owned_job(db, job_id, recruiter)])[0]


@router.put("/{job_id}", response_model=JobOut)
def update_job(
    job_id: int,
    payload: JobUpdate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    job = _owned_job(db, job_id, recruiter)
    if job.status == JobStatus.open and not payload.required_skills:
        raise HTTPException(422, "An open job needs at least one required skill.")
    for field, value in payload.model_dump().items():
        setattr(job, field, value)
    log_activity(db, recruiter.id, "job_updated", job_id=job.id)
    db.commit()
    db.refresh(job)
    return _out(db, [job])[0]


@router.patch("/{job_id}/status", response_model=JobOut)
def change_status(
    job_id: int,
    payload: JobStatusUpdate,
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    job = _owned_job(db, job_id, recruiter)
    if payload.status == job.status:
        return _out(db, [job])[0]
    if payload.status == JobStatus.open and not job.required_skills:
        raise HTTPException(422, "Add at least one required skill before publishing a job.")
    previous = job.status.value
    job.status = payload.status
    log_activity(
        db, recruiter.id, "job_status_changed", job_id=job.id,
        detail={"from": previous, "to": payload.status.value},
    )
    db.commit()
    db.refresh(job)
    return _out(db, [job])[0]