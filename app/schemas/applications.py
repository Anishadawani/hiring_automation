from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import Stage
from app.schemas.profile import ProfileOut

RECRUITER_SETTABLE_STAGES = {
    Stage.under_review,
    Stage.assessment,
    Stage.interview,
    Stage.shortlisted,
    Stage.offer,
    Stage.hired,
    Stage.rejected,
}


class ApplyRequest(BaseModel):
    job_id: int
    cover_letter: str | None = Field(default=None, max_length=3000)


class CandidateApplicationOut(BaseModel):
    """Candidate-facing view: stage only. Never includes scores, notes or decision reasons."""

    id: int
    job_id: int
    job_title: str
    stage: Stage
    cover_letter: str | None
    created_at: datetime
    updated_at: datetime


class StageUpdate(BaseModel):
    stage: Stage
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("stage")
    @classmethod
    def recruiter_can_set(cls, v: Stage) -> Stage:
        if v not in RECRUITER_SETTABLE_STAGES:
            raise ValueError("That stage cannot be set by a recruiter.")
        return v

    @model_validator(mode="after")
    def rejection_needs_reason(self):
        if self.reason is not None:
            self.reason = self.reason.strip() or None
        if self.stage == Stage.rejected and not self.reason:
            raise ValueError("A written reason is required to record a rejection.")
        return self


class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=4000)

    @field_validator("body")
    @classmethod
    def not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Note cannot be blank.")
        return v


class NoteOut(BaseModel):
    id: int
    author_name: str
    body: str
    created_at: datetime


class ScreeningOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    mode: str
    match_score: float
    score_breakdown: dict
    matched_skills: list[str]
    missing_skills: list[str]
    evidence: list[dict]
    ai_summary: str | None
    ai_model: str | None
    ai_error: str | None
    created_at: datetime
    advisory: str = "Advisory only. A human makes every hiring decision."


class ApplicationSummary(BaseModel):
    id: int
    job_id: int
    job_title: str
    candidate_id: int
    candidate_name: str
    candidate_email: str
    stage: Stage
    created_at: datetime
    updated_at: datetime
    latest_score: float | None = None
    latest_screening_mode: str | None = None


class ApplicationDetail(ApplicationSummary):
    cover_letter: str | None
    decision_reason: str | None
    decided_by_name: str | None
    decided_at: datetime | None
    has_resume: bool
    profile: ProfileOut | None
    notes: list[NoteOut]
    screenings: list[ScreeningOut]


class ActivityOut(BaseModel):
    id: int
    action: str
    job_id: int | None
    application_id: int | None
    detail: dict
    created_at: datetime


class DashboardOut(BaseModel):
    jobs_by_status: dict[str, int]
    applications_by_stage: dict[str, int]
    total_applications: int
    recent_activity: list[ActivityOut]