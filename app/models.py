"""All database tables for HireSense AI (SQLAlchemy 2.0 style).

Design notes:
- Enums are stored as plain strings (native_enum=False) so Alembic migrations
  stay simple.
- Lists/structured data (skills, education, rubrics) use JSON columns.
- Candidate profiles intentionally have NO age, gender, photo, nationality or
  similar fields: the platform never collects or scores protected traits.
"""
import enum
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def enum_column(enum_cls, length: int = 30):
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda e: [m.value for m in e],
    )


class Role(str, enum.Enum):
    candidate = "candidate"
    recruiter = "recruiter"


class JobStatus(str, enum.Enum):
    draft = "draft"
    open = "open"
    archived = "archived"


class Stage(str, enum.Enum):
    applied = "applied"
    under_review = "under_review"
    assessment = "assessment"
    interview = "interview"
    shortlisted = "shortlisted"
    offer = "offer"
    hired = "hired"
    rejected = "rejected"
    withdrawn = "withdrawn"


class AssessmentKind(str, enum.Enum):
    technical = "technical"
    behavioral = "behavioral"


class QuestionType(str, enum.Enum):
    multiple_choice = "multiple_choice"
    free_text = "free_text"


class AttemptStatus(str, enum.Enum):
    in_progress = "in_progress"
    submitted = "submitted"


class InterviewStatus(str, enum.Enum):
    scheduled = "scheduled"
    completed = "completed"
    cancelled = "cancelled"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[Role] = mapped_column(enum_column(Role, 20), index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    profile: Mapped[Optional["CandidateProfile"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )


class CandidateProfile(Base):
    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), unique=True
    )
    headline: Mapped[Optional[str]] = mapped_column(String(200))
    phone: Mapped[Optional[str]] = mapped_column(String(40))
    location: Mapped[Optional[str]] = mapped_column(String(200))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    skills: Mapped[list] = mapped_column(JSON, default=list)
    education: Mapped[list] = mapped_column(JSON, default=list)
    experience: Mapped[list] = mapped_column(JSON, default=list)
    resume_filename: Mapped[Optional[str]] = mapped_column(String(255))
    resume_path: Mapped[Optional[str]] = mapped_column(String(500))
    resume_text: Mapped[Optional[str]] = mapped_column(Text)
    resume_uploaded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    user: Mapped[User] = relationship(back_populates="profile")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    recruiter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[Optional[str]] = mapped_column(String(120))
    location: Mapped[Optional[str]] = mapped_column(String(200))
    employment_type: Mapped[str] = mapped_column(String(40), default="full_time")
    description: Mapped[str] = mapped_column(Text)
    required_skills: Mapped[list] = mapped_column(JSON, default=list)
    preferred_skills: Mapped[list] = mapped_column(JSON, default=list)
    min_years_experience: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[JobStatus] = mapped_column(
        enum_column(JobStatus, 20), default=JobStatus.draft, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    recruiter: Mapped[User] = relationship()
    applications: Mapped[list["Application"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("job_id", "candidate_id", name="uq_application_job_candidate"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    stage: Mapped[Stage] = mapped_column(
        enum_column(Stage, 30), default=Stage.applied, index=True
    )
    cover_letter: Mapped[Optional[str]] = mapped_column(Text)
    # Human decision fields: only a recruiter ever sets these.
    decision_reason: Mapped[Optional[str]] = mapped_column(Text)
    decided_by_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    job: Mapped[Job] = relationship(back_populates="applications")
    candidate: Mapped[User] = relationship(foreign_keys=[candidate_id])
    screenings: Mapped[list["ScreeningResult"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="ScreeningResult.created_at.desc()",
    )
    notes: Mapped[list["RecruiterNote"]] = relationship(
        back_populates="application",
        cascade="all, delete-orphan",
        order_by="RecruiterNote.created_at.desc()",
    )


class ScreeningResult(Base):
    """One screening run. Advisory only: never changes an application's stage."""

    __tablename__ = "screening_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    mode: Mapped[str] = mapped_column(String(20))  # "rules" or "claude"
    match_score: Mapped[float] = mapped_column(Float)
    score_breakdown: Mapped[dict] = mapped_column(JSON, default=dict)
    matched_skills: Mapped[list] = mapped_column(JSON, default=list)
    missing_skills: Mapped[list] = mapped_column(JSON, default=list)
    evidence: Mapped[list] = mapped_column(JSON, default=list)
    ai_summary: Mapped[Optional[str]] = mapped_column(Text)
    ai_model: Mapped[Optional[str]] = mapped_column(String(80))
    ai_error: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="screenings")


class RecruiterNote(Base):
    __tablename__ = "recruiter_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    application: Mapped[Application] = relationship(back_populates="notes")
    author: Mapped[User] = relationship()


class Assessment(Base):
    __tablename__ = "assessments"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), index=True)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[AssessmentKind] = mapped_column(enum_column(AssessmentKind, 20))
    instructions: Mapped[str] = mapped_column(Text, default="")
    time_limit_minutes: Mapped[Optional[int]] = mapped_column(Integer)
    is_published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    questions: Mapped[list["AssessmentQuestion"]] = relationship(
        back_populates="assessment",
        cascade="all, delete-orphan",
        order_by="AssessmentQuestion.position",
    )


class AssessmentQuestion(Base):
    __tablename__ = "assessment_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer, default=0)
    prompt: Mapped[str] = mapped_column(Text)
    question_type: Mapped[QuestionType] = mapped_column(enum_column(QuestionType, 30))
    options: Mapped[list] = mapped_column(JSON, default=list)  # multiple choice only
    correct_option: Mapped[Optional[int]] = mapped_column(Integer)  # never sent to candidates
    max_points: Mapped[int] = mapped_column(Integer, default=1)
    rubric: Mapped[list] = mapped_column(JSON, default=list)  # [{criterion, description, points}]

    assessment: Mapped[Assessment] = relationship(back_populates="questions")


class AssessmentAttempt(Base):
    __tablename__ = "assessment_attempts"
    __table_args__ = (
        UniqueConstraint("assessment_id", "application_id", name="uq_attempt_assessment_application"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    assessment_id: Mapped[int] = mapped_column(
        ForeignKey("assessments.id", ondelete="CASCADE"), index=True
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[AttemptStatus] = mapped_column(
        enum_column(AttemptStatus, 20), default=AttemptStatus.in_progress
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    total_score: Mapped[Optional[float]] = mapped_column(Float)
    max_score: Mapped[Optional[float]] = mapped_column(Float)

    answers: Mapped[list["AssessmentAnswer"]] = relationship(
        back_populates="attempt", cascade="all, delete-orphan"
    )


class AssessmentAnswer(Base):
    __tablename__ = "assessment_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_answer_attempt_question"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_attempts.id", ondelete="CASCADE"), index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("assessment_questions.id", ondelete="CASCADE")
    )
    answer_text: Mapped[Optional[str]] = mapped_column(Text)
    selected_option: Mapped[Optional[int]] = mapped_column(Integer)
    score: Mapped[Optional[float]] = mapped_column(Float)
    reviewer_comment: Mapped[Optional[str]] = mapped_column(Text)

    attempt: Mapped[AssessmentAttempt] = relationship(back_populates="answers")


class Interview(Base):
    __tablename__ = "interviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, default=45)
    mode: Mapped[str] = mapped_column(String(20), default="video")  # video / phone / onsite
    location: Mapped[Optional[str]] = mapped_column(Text)  # meeting link or address
    status: Mapped[InterviewStatus] = mapped_column(
        enum_column(InterviewStatus, 20), default=InterviewStatus.scheduled
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InterviewQuestion(Base):
    """AI-suggested interview questions, each tied to evidence from the resume."""

    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text)
    rationale: Mapped[str] = mapped_column(Text)
    evidence: Mapped[Optional[str]] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="claude")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ActivityLog(Base):
    """Audit trail powering the 'hiring activity' view."""

    __tablename__ = "activity_log"
    __table_args__ = (Index("ix_activity_created", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    application_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("applications.id", ondelete="SET NULL")
    )
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)