
"""Application settings, loaded from environment variables / the .env file."""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "development"
    database_url: str
    secret_key: str = Field(min_length=32)
    access_token_minutes: int = 60

    recruiter_invite_code: str = ""

    cors_origins: str = "http://localhost:5173"
    upload_dir: str = "uploads"
    max_resume_mb: int = 5

    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-5-5"
    ai_timeout_seconds: int = 30

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()
