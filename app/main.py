"""HireSense AI - FastAPI application entry point."""
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.routers import (
    applications,
    auth,
    candidate_profile,
    jobs,
    openings,
    recruiter_ai,
    recruiter_applications,
    recruiter_dashboard,
    resume,
)

settings = get_settings()

app = FastAPI(
    title="HireSense AI",
    version="0.3.1",
    description="Recruitment platform API. AI output is advisory and supports human review.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

for module in (
    auth,
    candidate_profile,
    resume,
    openings,
    applications,
    jobs,
    recruiter_applications,
    recruiter_ai,
    recruiter_dashboard,
):
    app.include_router(module.router)


@app.get("/api/health", tags=["system"])
def health(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(503, "Database unavailable.")
    return {
        "status": "ok",
        "environment": settings.environment,
        "ai_configured": bool(settings.anthropic_api_key),
    }