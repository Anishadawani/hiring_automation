def register_candidate(client):
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

    login_response = client.post(
        "/auth/login",
        json={
            "email": "candidate@example.com",
            "password": "StrongPassword123!",
        },
    )
    return login_response.json()["access_token"]


def test_candidate_can_get_profile(client):
    token = register_candidate(client)

    response = client.get(
        "/api/candidate/profile",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200


def test_candidate_can_update_profile(client):
    token = register_candidate(client)

    response = client.put(
        "/api/candidate/profile",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "headline": "Python Developer",
            "location": "Indore",
            "skills": ["Python", "SQL"],
        },
    )

    assert response.status_code == 200
    assert response.json()["headline"] == "Python Developer"
    assert "Python" in response.json()["skills"]


def test_profile_requires_authentication(client):
    response = client.get("/api/candidate/profile")

    assert response.status_code == 401