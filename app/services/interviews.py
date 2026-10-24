"""Interview rules: how a candidate joins, overlap checks, the consent notice, decision emails."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Interview, InterviewConsent, InterviewStatus
from app.services.assessments import aware

NOTICE_VERSION = "2026-10-1"

CONSENT_NOTICE = {
    "version": NOTICE_VERSION,
    "live_av": (
        "If you agree, your camera and microphone are used only during this live interview and are "
        "shared only with the interviewer. Your browser will ask for permission as well. "
        "You can check your devices first, turn your camera or microphone off at any time, "
        "or leave the call. The interview is not recorded and not transcribed. "
        "If you say no, or change your mind, your application is not affected and we will arrange "
        "another way to talk (for example a phone call)."
    ),
    "not_offered": (
        "Recording and transcription are not available in this version of HireSense, so you are "
        "not asked to agree to them."
    ),
}


def join_method(mode: str, location: str | None) -> str:
    if mode == "video":
        return "external_link" if location else "platform"
    return "phone" if mode == "phone" else "onsite"


def overlaps(a_start: datetime, a_minutes: int, b_start: datetime, b_minutes: int) -> bool:
    a0, b0 = aware(a_start), aware(b_start)
    return a0 < b0 + timedelta(minutes=b_minutes) and b0 < a0 + timedelta(minutes=a_minutes)


def get_choice(db: Session, interview_id: int, user_id: int, kind: str) -> InterviewConsent | None:
    return db.scalar(
        select(InterviewConsent).where(
            InterviewConsent.interview_id == interview_id,
            InterviewConsent.user_id == user_id,
            InterviewConsent.kind == kind,
        )
    )


def attendance_response(db: Session, interview_id: int, candidate_id: int) -> str:
    row = get_choice(db, interview_id, candidate_id, "attendance")
    if row is None:
        return "pending"
    return "confirmed" if row.granted else "declined"


def live_av_consent(db: Session, interview_id: int, candidate_id: int) -> bool | None:
    row = get_choice(db, interview_id, candidate_id, "live_av")
    return None if row is None else row.granted


def set_choice(db: Session, interview_id: int, user_id: int, kind: str, granted: bool, version: str | None) -> None:
    row = get_choice(db, interview_id, user_id, kind)
    if row is None:
        db.add(InterviewConsent(interview_id=interview_id, user_id=user_id, kind=kind, granted=granted, notice_version=version))
    else:
        row.granted = granted
        row.notice_version = version


def clear_choice(db: Session, interview_id: int, user_id: int, kind: str) -> None:
    row = get_choice(db, interview_id, user_id, kind)
    if row is not None:
        db.delete(row)


def is_open(interview: Interview) -> bool:
    return interview.status == InterviewStatus.scheduled


# ------------------------------------------------------------------ decision emails


def _when(interview: Interview) -> str:
    return aware(interview.scheduled_at).strftime("%A %d %B %Y at %H:%M UTC")


def draft_email(kind: str, candidate_name: str, job_title: str, interview: Interview | None = None) -> tuple[str, str]:
    """Plain, deterministic drafts. No scores, no AI output, and no internal decision reasons."""
    if kind == "interview_invitation" and interview is not None:
        method = join_method(interview.mode, interview.location)
        where = {
            "platform": "You can join from your HireSense account at the scheduled time. You will be able to "
            "test your camera and microphone first, and you choose whether to turn them on.",
            "external_link": f"Joining details: {interview.location}",
            "phone": f"We will call you on: {interview.location}",
            "onsite": f"Location: {interview.location}",
        }[method]
        return (
            f"Interview invitation: {job_title}",
            f"Dear {candidate_name},\n\nThank you for applying for the {job_title} role. We would like to invite you "
            f"to an interview.\n\nWhen: {_when(interview)} ({interview.duration_minutes} minutes)\n{where}\n\n"
            "Please confirm that you can attend in your HireSense account, or let us know if you need a different "
            "time or any adjustment to make the interview accessible for you.\n\nKind regards,\nThe Hiring Team",
        )
    if kind == "shortlist":
        return (
            f"Your application: {job_title}",
            f"Dear {candidate_name},\n\nThank you for applying for the {job_title} role. We are pleased to tell you "
            "that your application has been shortlisted. We will contact you soon about the next steps.\n\n"
            "Kind regards,\nThe Hiring Team",
        )
    if kind == "rejection":
        return (
            f"Your application: {job_title}",
            f"Dear {candidate_name},\n\nThank you for your interest in the {job_title} role and for the time you "
            "put into your application. After careful consideration we have decided not to move forward with "
            "your application at this time. We appreciate your interest and wish you every success.\n\n"
            "Kind regards,\nThe Hiring Team",
        )
    raise ValueError("Unknown email kind.")
