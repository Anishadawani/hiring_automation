
"""Test setup. Tests run against in-memory SQLite and NEVER call the Anthropic API."""
import os
import tempfile

# Must be set before the app is imported. Real environment variables beat .env.
os.environ["SECRET_KEY"] = "test-secret-key-for-pytest-only-0123456789abcdef"
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["RECRUITER_INVITE_CODE"] = "test-invite-code"
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["UPLOAD_DIR"] = tempfile.mkdtemp(prefix="hiresense-test-uploads-")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app import models  # noqa: E402,F401
from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402

import bcrypt  # noqa: E402
import app.routers.auth as auth_router  # noqa: E402


def _fast_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=4)).decode("utf-8")


auth_router.hash_password = _fast_hash
auth_router.DUMMY_HASH = _fast_hash("dummy-password")

PASSWORD = "CorrectHorse9!"
INVITE = "test-invite-code"

JOB = {
    "title": "Backend Engineer",
    "department": "Engineering",
    "location": "Indore",
    "employment_type": "full_time",
    "description": "Build and maintain REST APIs for our hiring platform.",
    "required_skills": ["Python", "FastAPI"],
    "preferred_skills": ["Docker"],
    "min_years_experience": 0,
}


@pytest.fixture()
def db_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def client(db_session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def make_headers(client, email: str, role: str, invite: str | None = None) -> dict:
    payload = {"email": email, "password": PASSWORD, "full_name": "Test User", "role": role}
    if invite:
        payload["invite_code"] = invite
    assert client.post("/api/auth/register", json=payload).status_code == 201
    login = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest.fixture()
def candidate_headers(client):
    return make_headers(client, "candidate@example.com", "candidate")


@pytest.fixture()
def recruiter_headers(client):
    return make_headers(client, "recruiter@example.com", "recruiter", INVITE)


@pytest.fixture()
def other_recruiter_headers(client):
    return make_headers(client, "other.recruiter@example.com", "recruiter", INVITE)


@pytest.fixture()
def other_candidate_headers(client):
    return make_headers(client, "other.candidate@example.com", "candidate")


def make_pdf_bytes(text: str) -> bytes:
    """Build a tiny, valid one-page PDF containing a single line of text."""
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 50 750 Td ({safe}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref_at = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_at}\n%%EOF\n".encode()
    )
    return bytes(out)


def create_job(client, headers, publish: bool = True, **overrides) -> dict:
    response = client.post("/api/jobs", headers=headers, json={**JOB, **overrides})
    assert response.status_code == 201, response.text
    job = response.json()
    if publish:
        response = client.patch(
            f"/api/jobs/{job['id']}/status",
            headers=headers,
            json={"status": "open"},
        )
        assert response.status_code == 200, response.text
        job = response.json()
    return job


def upload_resume(
    client,
    headers,
    text: str = "Python and FastAPI developer with Docker experience",
    name: str = "cv.pdf",
):
    data = make_pdf_bytes(text) if name.endswith(".pdf") else text.encode()
    response = client.post(
        "/api/candidate/resume",
        headers=headers,
        files={"file": (name, data, "application/octet-stream")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def apply_to(client, headers, job_id: int, cover_letter: str | None = None) -> dict:
    response = client.post(
        "/api/applications",
        headers=headers,
        json={"job_id": job_id, "cover_letter": cover_letter},
    )
    assert response.status_code == 201, response.text
    return response.json()
