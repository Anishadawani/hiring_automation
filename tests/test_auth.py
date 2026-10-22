from app.models import Role, User


def test_candidate_can_register(client):
    response = client.post(
        "/auth/register",
        json={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test Candidate",
            "role": "candidate",
        },
    )

    assert response.status_code == 201
    assert response.json()["email"] == "candidate@example.com"


def test_candidate_can_login(client):
    client.post(
        "/auth/register",
        json={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test Candidate",
            "role": "candidate",
        },
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
        },
    )

    assert response.status_code == 200
    assert "access_token" in response.json()


def test_login_rejects_wrong_password(client):
    client.post(
        "/auth/register",
        json={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
            "full_name": "Test Candidate",
            "role": "candidate",
        },
    )

    response = client.post(
        "/auth/login",
        json={
            "email": "candidate@example.com",
            "password": "WrongPassword123!",
        },
    )

    assert response.status_code == 401