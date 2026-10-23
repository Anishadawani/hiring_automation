from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.applications import ScreeningOut


class InterviewQuestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    question: str
    rationale: str
    evidence: str | None
    source: str  # "claude" = written by the AI, "template" = deterministic, no AI involved
    created_at: datetime


class AIReviewOut(ScreeningOut):
    ai_used: bool  # True only if Claude was actually called and its reply passed validation
    demo_mode: bool  # True when no API key is configured
    strengths: list[dict] = []
    gaps: list[dict] = []
    warnings: list[str] = []
    questions: list[InterviewQuestionOut] = []


class AIStatusOut(BaseModel):
    configured: bool
    mode: Literal["claude", "rules_only"]
    model: str | None
    notice: str