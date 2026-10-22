"""HireSense AI - FastAPI application entry point."""

import os

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.config import get_settings
from app.database import get_db
from app.routers import auth, candidate_profile
from app import screener

settings = get_settings()

app = FastAPI(
    title="HireSense AI",
    version="0.1.0",
    description=(
        "Recruitment platform API. "
        "AI output is advisory and supports human review."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(auth.router)
app.include_router(candidate_profile.router)


@app.get("/health", tags=["system"])
def legacy_health():
    return {"status": "ok"}


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


@app.post("/screen", tags=["Screening"])
async def screen_resume(
    job_description: str = Form(...),
    resume: UploadFile = File(...),
):
    configured_key = os.getenv("APP_API_KEY")

    if configured_key and resume.headers.get("authorization") != configured_key:
        raise HTTPException(status_code=401, detail="Invalid API key.")

    content = await resume.read()

    try:
        resume_text = screener.extract_text(resume.filename or "resume.txt", content)
        result = await run_in_threadpool(
            screener.screen_resume,
            resume_text,
            job_description,
        )
        return result.model_dump()
    except screener.ScreeningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    