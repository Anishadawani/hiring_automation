
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Education(BaseModel):
    institution: str = Field(min_length=1, max_length=200)
    degree: str = Field(min_length=1, max_length=200)
    field_of_study: str | None = Field(default=None, max_length=200)
    start_year: int | None = Field(default=None, ge=1950, le=2100)
    end_year: int | None = Field(default=None, ge=1950, le=2100)

    @model_validator(mode="after")
    def check_years(self):
        if self.start_year and self.end_year and self.end_year < self.start_year:
            raise ValueError("end_year cannot be before start_year.")
        return self


class Experience(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=200)
    start_date: date
    end_date: date | None = None
    description: str | None = Field(default=None, max_length=3000)

    @model_validator(mode="after")
    def check_dates(self):
        if self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date cannot be before start_date.")
        return self


def _clean_skills(skills: list[str]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in skills:
        skill = raw.strip()
        if not skill:
            continue
        if len(skill) > 60:
            raise ValueError("Each skill must be 60 characters or fewer.")
        key = skill.casefold()
        if key not in seen:
            seen.add(key)
            cleaned.append(skill)
    return cleaned


class ProfileUpdate(BaseModel):
    headline: str | None = Field(default=None, max_length=200)
    phone: str | None = Field(default=None, max_length=40)
    location: str | None = Field(default=None, max_length=200)
    summary: str | None = Field(default=None, max_length=4000)
    skills: list[str] = Field(default_factory=list, max_length=60)
    education: list[Education] = Field(default_factory=list, max_length=20)
    experience: list[Experience] = Field(default_factory=list, max_length=30)

    @field_validator("skills")
    @classmethod
    def normalise_skills(cls, v: list[str]) -> list[str]:
        return _clean_skills(v)


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    headline: str | None
    phone: str | None
    location: str | None
    summary: str | None
    skills: list[str]
    education: list[Education]
    experience: list[Experience]
    resume_filename: str | None
    resume_uploaded_at: datetime | None
    updated_at: datetime
