from pathlib import Path

import pytest

from app.config import get_settings
from app.models import CandidateProfile
from app.services.resume import ResumeError, resolve_resume_path, safe_display_name
from tests.conftest import make_pdf_bytes, upload_resume


def post_file(client, headers, name, data):
    return client.post(
        "/api/candidate/resume", headers=headers, files={"file": (name, data, "application/octet-stream")}
    )


def stored_path(db_session) -> Path:
    profile = db_session.query(CandidateProfile).one()
    return Path(get_settings().upload_dir).resolve() / profile.resume_path


def test_upload_pdf_extracts_text_and_stores_file(client, candidate_headers, db_session):
    body = upload_resume(client, candidate_headers, "Python FastAPI PostgreSQL")
    assert body["resume_filename"] == "cv.pdf"
    assert body["resume_uploaded_at"] is not None
    profile = db_session.query(CandidateProfile).one()
    assert "Python" in profile.resume_text
    assert stored_path(db_session).is_file()


def test_upload_text_resume(client, candidate_headers, db_session):
    upload_resume(client, candidate_headers, "Plain text resume with Python", name="cv.txt")
    assert "Plain text" in db_session.query(CandidateProfile).one().resume_text


def test_resume_text_is_not_exposed_in_profile_api(client, candidate_headers):
    upload_resume(client, candidate_headers)
    assert "resume_text" not in client.get("/api/candidate/profile", headers=candidate_headers).json()


def test_unsupported_extension_rejected(client, candidate_headers):
    assert post_file(client, candidate_headers, "virus.exe", b"MZ...").status_code == 422


def test_fake_pdf_rejected(client, candidate_headers):
    assert post_file(client, candidate_headers, "cv.pdf", b"just text, not a pdf").status_code == 422


def test_corrupt_pdf_rejected(client, candidate_headers):
    assert post_file(client, candidate_headers, "cv.pdf", b"%PDF-1.4\ngarbage garbage").status_code == 422


def test_empty_file_rejected(client, candidate_headers):
    assert post_file(client, candidate_headers, "cv.txt", b"").status_code == 400


def test_whitespace_only_text_rejected(client, candidate_headers):
    assert post_file(client, candidate_headers, "cv.txt", b"   \n  ").status_code == 422


def test_oversized_file_rejected(client, candidate_headers, monkeypatch):
    monkeypatch.setattr(get_settings(), "max_resume_mb", 1)
    big = b"a" * (1024 * 1024 + 1)
    assert post_file(client, candidate_headers, "cv.txt", big).status_code == 413


def test_recruiters_cannot_upload_and_anonymous_cannot(client, recruiter_headers):
    data = make_pdf_bytes("Python")
    assert post_file(client, recruiter_headers, "cv.pdf", data).status_code == 403
    assert client.post("/api/candidate/resume", files={"file": ("cv.pdf", data)}).status_code == 401


def test_replacing_resume_removes_the_old_file(client, candidate_headers, db_session):
    upload_resume(client, candidate_headers, "first version Python")
    first = stored_path(db_session)
    upload_resume(client, candidate_headers, "second version FastAPI")
    db_session.expire_all()
    second = stored_path(db_session)
    assert second != first
    assert second.is_file() and not first.exists()


def test_delete_resume_clears_everything(client, candidate_headers, db_session):
    upload_resume(client, candidate_headers)
    path = stored_path(db_session)
    r = client.delete("/api/candidate/resume", headers=candidate_headers)
    assert r.status_code == 200 and r.json()["resume_filename"] is None
    profile = db_session.query(CandidateProfile).one()
    assert profile.resume_text is None and profile.resume_path is None
    assert not path.exists()


def test_filename_is_sanitised():
    assert safe_display_name("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_display_name("my résumé (final).pdf") == "my r_sum_ _final_.pdf"
    assert safe_display_name(None) == "resume"


def test_stored_paths_cannot_escape_upload_folder():
    with pytest.raises(ResumeError):
        resolve_resume_path("../../etc/passwd")