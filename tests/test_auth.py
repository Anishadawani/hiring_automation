
from tests.conftest import PASSWORD

CANDIDATE = {
    "email": "ada@example.com",
    "password": PASSWORD,
    "full_name": "Ada Lovelace",
    "role": "candidate",
}


def test_health_endpoint(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["ai_configured"] is False


def test_register_candidate(client):
    r = client.post("/api/auth/register", json=CANDIDATE)
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "ada@example.com"
    assert body["role"] == "candidate"
    assert "password" not in body and "password_hash" not in body


def test_duplicate_email_rejected_case_insensitively(client):
    assert client.post("/api/auth/register", json=CANDIDATE).status_code == 201
    again = {**CANDIDATE, "email": "ADA@Example.com"}
    assert client.post("/api/auth/register", json=again).status_code == 409


def test_weak_passwords_rejected(client):
    for bad in ["short1", "onlyletterslong", "1234567890123"]:
        r = client.post("/api/auth/register", json={**CANDIDATE, "password": bad})
        assert r.status_code == 422, bad


def test_recruiter_needs_invite_code(client):
    base = {**CANDIDATE, "email": "rec@example.com", "role": "recruiter"}
    assert client.post("/api/auth/register", json=base).status_code == 403
    wrong = {**base, "invite_code": "nope"}
    assert client.post("/api/auth/register", json=wrong).status_code == 403
    ok = {**base, "invite_code": "test-invite-code"}
    assert client.post("/api/auth/register", json=ok).status_code == 201


def test_login_success_and_failure(client):
    client.post("/api/auth/register", json=CANDIDATE)
    good = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": PASSWORD},
    )
    assert good.status_code == 200
    assert good.json()["token_type"] == "bearer"
    assert good.json()["user"]["role"] == "candidate"

    bad = client.post(
        "/api/auth/login",
        json={"email": "ada@example.com", "password": "WrongPass1!"},
    )
    assert bad.status_code == 401
    unknown = client.post(
        "/api/auth/login",
        json={"email": "who@example.com", "password": PASSWORD},
    )
    assert unknown.status_code == 401
    assert bad.json()["detail"] == unknown.json()["detail"]


def test_me_requires_valid_token(client, candidate_headers):
    assert client.get("/api/auth/me").status_code == 401
    assert client.get(
        "/api/auth/me",
        headers={"Authorization": "Bearer garbage"},
    ).status_code == 401
    token = candidate_headers["Authorization"]
    tampered = {
        "Authorization": token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    }
    assert client.get("/api/auth/me", headers=tampered).status_code == 401
    r = client.get("/api/auth/me", headers=candidate_headers)
    assert r.status_code == 200
    assert r.json()["email"] == "candidate@example.com"
