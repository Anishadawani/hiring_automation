from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import InterviewStatus

Mode = Literal["video", "phone", "onsite"]
JoinMethod = Literal["platform", "external_link", "phone", "onsite"]
Response = Literal["pending", "confirmed", "declined"]


def _require_timezone(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("Include a timezone, for example 2026-11-02T10:00:00+05:30 or ...Z.")
    return v


class InterviewIn(BaseModel):
    scheduled_at: datetime
    duration_minutes: int = Field(default=45, ge=15, le=240)
    mode: Mode = "video"
    # video + empty location = the HireSense live room; video + a link = an external meeting
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)  # internal: candidates never see this

    @field_validator("scheduled_at")
    @classmethod
    def valid_time(cls, v: datetime) -> datetime:
        v = _require_timezone(v)
        if v < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError("The interview time must be in the future.")
        return v

    @field_validator("location", "notes")
    @classmethod
    def clean(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @model_validator(mode="after")
    def location_rules(self):
        if self.mode in ("phone", "onsite") and not self.location:
            raise ValueError("Add the phone number or address for this interview.")
        return self


class InterviewUpdate(BaseModel):
    scheduled_at: datetime | None = None
    duration_minutes: int | None = Field(default=None, ge=15, le=240)
    mode: Mode | None = None
    location: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    status: InterviewStatus | None = None

    @field_validator("scheduled_at")
    @classmethod
    def valid_time(cls, v: datetime | None) -> datetime | None:
        if v is None:
            return v
        v = _require_timezone(v)
        if v < datetime.now(timezone.utc) - timedelta(minutes=5):
            raise ValueError("The interview time must be in the future.")
        return v

    @field_validator("status")
    @classmethod
    def only_closing_statuses(cls, v: InterviewStatus | None) -> InterviewStatus | None:
        if v == InterviewStatus.scheduled:
            raise ValueError("To change the time, send scheduled_at instead.")
        return v


class InterviewOut(BaseModel):
    id: int
    application_id: int
    scheduled_at: datetime
    duration_minutes: int
    mode: Mode
    location: str | None
    notes: str | None
    status: InterviewStatus
    join_method: JoinMethod
    candidate_response: Response
    live_av_consent: bool | None  # None = the candidate has not answered yet
    created_at: datetime


class RecruiterInterviewRow(InterviewOut):
    candidate_name: str
    job_title: str


class CandidateInterviewOut(BaseModel):
    """What a candidate sees. Never includes the recruiter's internal notes."""

    id: int
    application_id: int
    job_title: str
    scheduled_at: datetime
    duration_minutes: int
    mode: Mode
    location: str | None
    status: InterviewStatus
    join_method: JoinMethod
    my_response: Response
    live_av_consent: bool | None
    upcoming: bool


class RespondIn(BaseModel):
    response: Literal["confirmed", "declined"]


class ConsentIn(BaseModel):
    # Only live camera/microphone is offered. Recording and transcription are not built, so
    # the API refuses to collect consent for them.
    kind: Literal["live_av"] = "live_av"
    granted: bool


class ConsentNoticeOut(BaseModel):
    version: str
    live_av: str
    not_offered: str


class EmailDraftOut(BaseModel):
    kind: Literal["interview_invitation", "shortlist", "rejection"]
    to: str
    subject: str
    body: str
    note: str = "Draft only. HireSense never sends email. A person reviews it and sends it."
    requires_human_review: bool = True
