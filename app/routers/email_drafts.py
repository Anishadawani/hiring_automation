"""Decision email drafts. Drafts only: HireSense never sends email.

A draft is only available when a person has already recorded the matching decision, so an AI
score or recommendation can never produce a rejection or shortlist message on its own.
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_recruiter
from app.models import Interview, InterviewStatus, Stage, User
from app.schemas.interviews import EmailDraftOut
from app.services import interviews as svc
from app.services.access import owned_application
from app.services.activity import log_activity

router = APIRouter(prefix="/api/recruiter", tags=["email drafts"])


@router.get("/applications/{application_id}/email-draft", response_model=EmailDraftOut)
def email_draft(
    application_id: int,
    kind: Literal["interview_invitation", "shortlist", "rejection"],
    recruiter: User = Depends(require_recruiter),
    db: Session = Depends(get_db),
):
    application = owned_application(db, application_id, recruiter)
    candidate, job = application.candidate, application.job
    interview = None

    if kind == "rejection" and application.stage != Stage.rejected:
        raise HTTPException(409, "A rejection email can only be drafted after a person has recorded the rejection.")
    if kind == "shortlist" and application.stage not in (Stage.shortlisted, Stage.offer, Stage.hired):
        raise HTTPException(409, "A shortlist email can only be drafted after a person has shortlisted the candidate.")
    if kind == "interview_invitation":
        interview = db.scalar(
            select(Interview)
            .where(Interview.application_id == application.id, Interview.status == InterviewStatus.scheduled)
            .order_by(Interview.scheduled_at)
        )
        if interview is None:
            raise HTTPException(409, "Schedule an interview first.")

    subject, body = svc.draft_email(kind, candidate.full_name, job.title, interview)
    log_activity(db, recruiter.id, "email_drafted", job_id=job.id, application_id=application.id, detail={"kind": kind})
    db.commit()
    return EmailDraftOut(kind=kind, to=candidate.email, subject=subject, body=body)
