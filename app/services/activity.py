"""Audit trail helper. Callers are responsible for committing the session."""
from sqlalchemy.orm import Session

from app.models import ActivityLog


def log_activity(
    db: Session,
    actor_id: int | None,
    action: str,
    job_id: int | None = None,
    application_id: int | None = None,
    detail: dict | None = None,
) -> None:
    db.add(
        ActivityLog(
            actor_id=actor_id,
            action=action,
            job_id=job_id,
            application_id=application_id,
            detail=detail or {},
        )
    )