"""FastAPI service: POST a resume + job description, get a structured screening result."""
import logging
import os

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from app import screener

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="AI Hiring Automation", version="1.0.0")

MAX_UPLOAD_BYTES = 5 * 1024 * 1024


def check_key(x_api_key: str | None = Header(default=None)):
    expected = os.getenv("APP_API_KEY")
    if expected and x_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid API key")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/screen", response_model=screener.ScreeningResult, dependencies=[Depends(check_key)])
async def screen(job_description: str = Form(...), resume: UploadFile = File(...)):
    data = await resume.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Resume larger than 5 MB")
    if not job_description.strip():
        raise HTTPException(status_code=400, detail="job_description is empty")
    try:
        text = screener.extract_text(resume.filename, data)
        return screener.screen_resume(text, job_description)
    except screener.ScreeningError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
