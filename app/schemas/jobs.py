from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models import JobStatus
from app.schemas.profile import _clean_skills as clean_skills

EmploymentType = Literal["full_time", "part_time", "contract", "internship"]


class JobBase(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    department: str | None = Field(default=None, max_length=120)
    location: str | None = Field(default=None, max_length=200)
    employment_type: EmploymentType = "full_time"
    description: str = Field(min_length=20, max_length=10000)
    required_skills: list[str] = Field(default_factory=list, max_length=30)
    preferred_skills: list[str] = Field(default_factory=list, max_length=30)
    min_years_experience: int = Field(default=0, ge=0, le=40)

    @field_validator("title")
    @classmethod
    def clean_title(cls, v: str) -> str:
        v = v.strip()
        if len(v) < 3:
            raise ValueError("Title must be at least 3 characters.")
        return v

    @field_validator("required_skills", "preferred_skills")
    @classmethod
    def normalise_skills(cls, v: list[str]) -> list[str]:
        return clean_skills(v)

    @model_validator(mode="after")
    def drop_duplicate_preferred(self):
        required = {s.casefold() for s in self.required_skills}
        self.preferred_skills = [s for s in self.preferred_skills if s.casefold() not in required]
        return self


class JobCreate(JobBase):
    status: JobStatus = JobStatus.draft

    @field_validator("status")
    @classmethod
    def not_archived(cls, v: JobStatus) -> JobStatus:
        if v == JobStatus.archived:
            raise ValueError("A new job cannot be created as archived.")
        return v


class JobUpdate(JobBase):
    pass


class JobStatusUpdate(BaseModel):
    status: JobStatus


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    department: str | None
    location: str | None
    employment_type: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    min_years_experience: int
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    application_count: int = 0


class OpeningOut(BaseModel):
    """What a candidate sees: no recruiter details, no internal fields."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    department: str | None
    location: str | None
    employment_type: str
    description: str
    required_skills: list[str]
    preferred_skills: list[str]
    min_years_experience: int
    created_at: datetime
    has_applied: bool = False