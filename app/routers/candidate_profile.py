
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import require_candidate
from app.models import CandidateProfile, User
from app.schemas.profile import ProfileOut, ProfileUpdate

router = APIRouter(prefix="/api/candidate", tags=["candidate profile"])


def _get_or_create_profile(db: Session, user: User) -> CandidateProfile:
    profile = user.profile
    if profile is None:
        profile = CandidateProfile(user_id=user.id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


@router.get("/profile", response_model=ProfileOut)
def get_profile(user: User = Depends(require_candidate), db: Session = Depends(get_db)):
    return _get_or_create_profile(db, user)


@router.put("/profile", response_model=ProfileOut)
def update_profile(
    payload: ProfileUpdate,
    user: User = Depends(require_candidate),
    db: Session = Depends(get_db),
):
    profile = _get_or_create_profile(db, user)
    profile.headline = payload.headline
    profile.phone = payload.phone
    profile.location = payload.location
    profile.summary = payload.summary
    profile.skills = payload.skills
    profile.education = [e.model_dump(mode="json") for e in payload.education]
    profile.experience = [x.model_dump(mode="json") for x in payload.experience]
    db.commit()
    db.refresh(profile)
    return profile
