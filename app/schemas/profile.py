
"""Candidate profile request and response schemas."""

from pydantic import BaseModel, Field


class EducationItem(BaseModel):
    degree: str = Field(min_length=1, max_length=200)
    institution: str = Field(min_length=1, max_length=200)
    year: str | None = None


class ExperienceItem(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    description: str | None = None
    years: float = Field(default=0, ge=0, le=60)


class ProfileUpdateRequest(BaseModel):
    headline: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=3000)
    skills: list[str] = Field(default_factory=list, max_length=100)
    education: list[EducationItem] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    id: int
    user_id: int
    headline: str | None = None
    phone: str | None = None
    location: str | None = None
    summary: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    experience: list[dict] = Field(default_factory=list)

    model_config = {"from_attributes": True}
