from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models import AssessmentKind, AttemptStatus, QuestionType


class RubricCriterion(BaseModel):
    criterion: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    points: int = Field(ge=1, le=100)

    @field_validator("criterion", "description")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class QuestionIn(BaseModel):
    prompt: str = Field(min_length=5, max_length=4000)
    question_type: QuestionType
    options: list[str] = Field(default_factory=list, max_length=6)
    correct_option: int | None = None
    max_points: int = Field(default=1, ge=1, le=100)
    rubric: list[RubricCriterion] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def check_by_type(self):
        self.prompt = self.prompt.strip()
        if len(self.prompt) < 5:
            raise ValueError("Question text must be at least 5 characters.")
        if self.question_type == QuestionType.multiple_choice:
            options = [o.strip() for o in self.options]
            if not 2 <= len(options) <= 6 or any(not o or len(o) > 300 for o in options):
                raise ValueError("Multiple-choice questions need 2 to 6 non-empty options (max 300 characters).")
            if len({o.casefold() for o in options}) != len(options):
                raise ValueError("Options must be different from each other.")
            if self.correct_option is None or not 0 <= self.correct_option < len(options):
                raise ValueError("correct_option must be the position (starting at 0) of one of the options.")
            if self.rubric:
                raise ValueError("Multiple-choice questions are scored automatically and do not use a rubric.")
            self.options = options
        else:
            if self.options or self.correct_option is not None:
                raise ValueError("Free-text questions cannot have options or a correct option.")
            if self.rubric and sum(c.points for c in self.rubric) != self.max_points:
                raise ValueError(f"Rubric points must add up to max_points ({self.max_points}).")
        return self


class AssessmentIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    kind: AssessmentKind
    instructions: str = Field(default="", max_length=4000)
    time_limit_minutes: int | None = Field(default=None, ge=5, le=240)
    questions: list[QuestionIn] = Field(default_factory=list, max_length=50)

    @field_validator("title", "instructions")
    @classmethod
    def strip(cls, v: str) -> str:
        return v.strip()


class StatusUpdate(BaseModel):
    is_published: bool


class QuestionOut(BaseModel):
    id: int
    position: int
    prompt: str
    question_type: QuestionType
    options: list[str]
    correct_option: int | None
    max_points: int
    rubric: list[RubricCriterion]


class AssessmentSummary(BaseModel):
    id: int
    job_id: int
    title: str
    kind: AssessmentKind
    is_published: bool
    time_limit_minutes: int | None
    question_count: int
    attempt_count: int
    created_at: datetime


class AssessmentDetail(AssessmentSummary):
    instructions: str
    questions: list[QuestionOut]


class RubricOut(BaseModel):
    question_id: int
    rubric: list[RubricCriterion]
    source: Literal["claude", "template"]
    ai_used: bool
    warnings: list[str] = []
    notice: str | None = None


# ---------------------------------------------------------------- candidate-facing


class CandidateQuestionOut(BaseModel):
    """What a candidate sees: never the correct option and never the rubric."""

    id: int
    position: int
    prompt: str
    question_type: QuestionType
    options: list[str]
    max_points: int


class AnswerIn(BaseModel):
    answer_text: str | None = Field(default=None, max_length=10_000)
    selected_option: int | None = None


class SavedAnswer(BaseModel):
    question_id: int
    answer_text: str | None
    selected_option: int | None


class AttemptOut(BaseModel):
    """Candidate view of an attempt. Never includes scores, correct answers or rubrics."""

    attempt_id: int
    assessment_id: int
    application_id: int
    title: str
    kind: AssessmentKind
    instructions: str
    time_limit_minutes: int | None
    status: AttemptStatus
    started_at: datetime
    deadline: datetime | None
    seconds_remaining: int | None
    total_questions: int
    answered_count: int
    questions: list[CandidateQuestionOut]
    answers: list[SavedAnswer]


class CandidateTaskOut(BaseModel):
    application_id: int
    job_title: str
    assessment_id: int
    title: str
    kind: AssessmentKind
    time_limit_minutes: int | None
    question_count: int
    status: Literal["not_started", "in_progress", "submitted"]
    attempt_id: int | None


# ---------------------------------------------------------------- recruiter results


class AnswerResult(BaseModel):
    answer_id: int | None
    question_id: int
    position: int
    prompt: str
    question_type: QuestionType
    options: list[str]
    correct_option: int | None
    max_points: int
    rubric: list[RubricCriterion]
    answer_text: str | None
    selected_option: int | None
    auto_graded: bool
    score: float | None
    reviewer_comment: str | None
    needs_review: bool


class AttemptSummary(BaseModel):
    attempt_id: int
    application_id: int
    candidate_name: str
    candidate_email: str
    status: AttemptStatus
    started_at: datetime
    submitted_at: datetime | None
    total_score: float | None
    max_score: float | None
    pending_review: int


class AttemptResult(AttemptSummary):
    assessment_id: int
    assessment_title: str
    kind: AssessmentKind
    percentage: float | None  # only once every answer has a score
    answers: list[AnswerResult]
    advisory: str = "Assessment results are one input. A person makes every hiring decision."


class GradeIn(BaseModel):
    score: float = Field(ge=0)
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("comment")
    @classmethod
    def clean(cls, v: str | None) -> str | None:
        return (v or "").strip() or None
