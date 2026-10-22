from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import Role


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    full_name: str = Field(min_length=1, max_length=200)
    role: Role
    invite_code: str | None = Field(default=None, max_length=200)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return str(v).lower()

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name cannot be blank.")
        return v

    @field_validator("password")
    @classmethod
    def password_rules(cls, v: str) -> str:
        # bcrypt only uses the first 72 bytes, so we cap there explicitly.
        if len(v.encode("utf-8")) > 72:
            raise ValueError("Password must be at most 72 bytes long.")
        if not any(c.isalpha() for c in v) or not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one letter and one number.")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)

    @field_validator("email")
    @classmethod
    def lowercase_email(cls, v: str) -> str:
        return str(v).lower()


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: str
    full_name: str
    role: Role
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut