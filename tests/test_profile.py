
VALID_PROFILE = {
    "headline": "Backend developer",
    "location": "Indore, India",
    "summary": "Building APIs.",
    "skills": ["Python", " python ", "FastAPI", ""],
    "education": [
        {
            "institution": "Example University",
            "degree": "B.Tech",
            "start_year": 2018,
            "end_year": 2022,
        }
    ],
    "experience": [
        {
            "company": "Acme",
            "title": "Developer",
            "start_date": "2022-07-01",
            "end_date": None,
        }
    ],
}


def test_new_candidate_has_empty_profile(client, candidate_headers):
    r = client.get("/api/candidate/profile", headers=candidate_headers)
    assert r.status_code == 200
    assert r.json()["skills"] == []
    assert r.json()["resume_filename"] is None


def test_update_profile_normalises_and_persists(client, candidate_headers):
    r = client.put(
        "/api/candidate/profile",
        headers=candidate_headers,
        json=VALID_PROFILE,
    )
    assert r.status_code == 200
    assert r.json()["skills"] == ["Python", "FastAPI"]

    again = client.get(
        "/api/candidate/profile",
        headers=candidate_headers,
    ).json()
    assert again["headline"] == "Backend developer"
    assert again["education"][0]["institution"] == "Example University"
    assert again["experience"][0]["start_date"] == "2022-07-01"


def test_invalid_education_years_rejected(client, candidate_headers):
    bad = {
        **VALID_PROFILE,
        "education": [
            {
                "institution": "X",
                "degree": "Y",
                "start_year": 2022,
                "end_year": 2018,
            }
        ],
    }
    assert client.put(
        "/api/candidate/profile",
        headers=candidate_headers,
        json=bad,
    ).status_code == 422


def test_recruiter_cannot_use_candidate_profile(client, recruiter_headers):
    assert client.get(
        "/api/candidate/profile",
        headers=recruiter_headers,
    ).status_code == 403


def test_profile_requires_login(client):
    assert client.get("/api/candidate/profile").status_code == 401
