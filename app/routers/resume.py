from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.deps import require_candidate
from app.models import CandidateProfile, User, utcnow
from app.schemas.profile import ProfileOut
from app.services.resume import (
    ResumeError,
    delete_resume_file,
    extract_text,
    safe_display_name,
    store_resume,
)

router = APIRouter(prefix="/api/candidate/resume", tags=["candidate resume"])


def _profile(db: Session, user: User) -> CandidateProfile:
    profile = user.profile
    if profile is None:
        profile = CandidateProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.post("", response_model=ProfileOut)
async def upload_resume(
    file: UploadFile = File(...),
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    settings = get_settings()
    max_bytes = settings.max_resume_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)  # read one byte past the limit to detect oversize
    if len(data) > max_bytes:
        raise HTTPException(413, f"Resume must be {settings.max_resume_mb} MB or smaller.")
    if not data:
        raise HTTPException(400, "The uploaded file is empty.")
    try:
        text = extract_text(file.filename, data)
    except ResumeError as exc:
        raise HTTPException(422, str(exc))

    profile = _profile(db, user)
    old_key = profile.resume_path
    profile.resume_path = store_resume(user.id, file.filename, data)
    profile.resume_filename = safe_display_name(file.filename)
    profile.resume_text = text
    profile.resume_uploaded_at = utcnow()
    db.commit()
    db.refresh(profile)
    delete_resume_file(old_key)
    return profile


@router.delete("", response_model=ProfileOut)
def delete_resume(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    profile = _profile(db, user)
    old_key = profile.resume_path
    profile.resume_path = None
    profile.resume_filename = None
    profile.resume_text = None
    profile.resume_uploaded_at = None
    db.commit()
    db.refresh(profile)
    delete_resume_file(old_key)
    return profile