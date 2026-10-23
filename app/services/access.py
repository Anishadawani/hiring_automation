"""Shared access-control helper for recruiter-only routes."""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Job, User


def owned_application(db: Session, application_id: int, recruiter: User) -> Application:
    """Return the application only if it belongs to one of this recruiter's jobs.

    Returns 404 (not 403) for other recruiters' applications so their existence is not revealed.
    """
    application = db.scalar(
        select(Application)
        .join(Job, Application.job_id == Job.id)
        .where(Application.id == application_id, Job.recruiter_id == recruiter.id)
    )
    if application is None:
        raise HTTPException(404, "Application not found.")
    return application