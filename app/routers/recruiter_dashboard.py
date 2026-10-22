"""Recruiter dashboard. Every number is a live count from the database."""
from fastapi import APIRouter, Depends
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_recruiter
from app.models import ActivityLog, Application, Job, JobStatus, Stage, User
from app.schemas.applications import ActivityOut, DashboardOut

router = APIRouter(prefix="/api/recruiter", tags=["recruiter dashboard"])


@router.get("/dashboard", response_model=DashboardOut)
def dashboard(recruiter: User = Depends(require_recruiter), db: Session = Depends(get_db)):
    job_counts = dict(
        db.execute(
            select(Job.status, func.count()).where(Job.recruiter_id == recruiter.id).group_by(Job.status)
        ).all()
    )
    stage_counts = dict(
        db.execute(
            select(Application.stage, func.count())
            .join(Job, Application.job_id == Job.id)
            .where(Job.recruiter_id == recruiter.id)
            .group_by(Application.stage)
        ).all()
    )
    my_job_ids = select(Job.id).where(Job.recruiter_id == recruiter.id)
    activity = db.scalars(
        select(ActivityLog)
        .where(or_(ActivityLog.job_id.in_(my_job_ids), ActivityLog.actor_id == recruiter.id))
        .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        .limit(15)
    ).all()
    return DashboardOut(
        jobs_by_status={s.value: job_counts.get(s, 0) for s in JobStatus},
        applications_by_stage={s.value: stage_counts.get(s, 0) for s in Stage},
        total_applications=sum(stage_counts.values()),
        recent_activity=[
            ActivityOut(
                id=a.id, action=a.action, job_id=a.job_id,
                application_id=a.application_id, detail=a.detail or {}, created_at=a.created_at,
            )
            for a in activity
        ],
    )