"""Candidate-facing job browsing: open jobs only."""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_candidate
from app.models import Application, Job, JobStatus, User
from app.schemas.common import Page
from app.schemas.jobs import EmploymentType, OpeningOut
from app.services.query import contains_pattern

router = APIRouter(prefix="/api/openings", tags=["openings (candidate)"])


def _applied_job_ids(db: Session, user: User) -> set[int]:
    return set(db.scalars(select(Application.job_id).where(Application.candidate_id == user.id)).all())


@router.get("", response_model=Page[OpeningOut])
def browse_openings(
    q: str | None = Query(default=None, max_length=100),
    location: str | None = Query(default=None, max_length=100),
    employment_type: EmploymentType | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    filters = [Job.status == JobStatus.open]
    if q and q.strip():
        pattern = contains_pattern(q)
        filters.append(Job.title.ilike(pattern, escape="\\") | Job.description.ilike(pattern, escape="\\"))
    if location and location.strip():
        filters.append(Job.location.ilike(contains_pattern(location), escape="\\"))
    if employment_type:
        filters.append(Job.employment_type == employment_type)
    total = db.scalar(select(func.count()).select_from(Job).where(*filters)) or 0
    jobs = db.scalars(
        select(Job).where(*filters).order_by(Job.created_at.desc(), Job.id.desc()).limit(limit).offset(offset)
    ).all()
    applied = _applied_job_ids(db, user)
    items = [OpeningOut.model_validate(j).model_copy(update={"has_applied": j.id in applied}) for j in jobs]
    return Page[OpeningOut](items=items, total=total)


@router.get("/{job_id}", response_model=OpeningOut)
def get_opening(job_id: int, user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    job = db.scalar(select(Job).where(Job.id == job_id, Job.status == JobStatus.open))
    if job is None:
        raise HTTPException(404, "This job is not available.")
    return OpeningOut.model_validate(job).model_copy(
        update={"has_applied": job.id in _applied_job_ids(db, user)}
    )