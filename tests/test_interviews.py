"""Interview scheduling, invitations, consent and decision-email drafts."""
from datetime import datetime, timedelta, timezone

import pytest

from tests.conftest import apply_to, create_job, upload_resume

R = "/api/recruiter"
C = "/api/candidate"


def when(hours=48, minutes=0):
    return (datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)).replace(microsecond=0).isoformat()


def setup(client, recruiter_headers, candidate_headers):
    job = create_job(client, recruiter_headers, title="Platform Engineer")
    upload_resume(client, candidate_headers)
    return job, apply_to(client, candidate_headers, job["id"])


def schedule(client, headers, application, **body):
    payload = {"scheduled_at": when(), "duration_minutes": 45, "mode": "video", **body}
    return client.post(f"{R}/applications/{application['id']}/interviews", headers=headers, json=payload)


# --------------------------------------------------------------------- scheduling


def test_schedule_a_platform_video_interview(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    r = schedule(client, recruiter_headers, application, notes="Check API design depth")
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "scheduled" and body["join_method"] == "platform"
    assert body["candidate_response"] == "pending" and body["live_av_consent"] is None
    assert body["notes"] == "Check API design depth"

    listed = client.get(f"{R}/applications/{application['id']}/interviews", headers=recruiter_headers).json()
    assert [i["id"] for i in listed] == [body["id"]]
    overview = client.get(f"{R}/interviews", headers=recruiter_headers).json()
    assert overview[0]["candidate_name"] == "Test User" and overview[0]["job_title"] == "Platform Engineer"

    # Scheduling is not a decision: the stage is untouched.
    assert client.get(f"{R}/applications/{application['id']}", headers=recruiter_headers).json()["stage"] == "applied"


@pytest.mark.parametrize(
    "body, join",
    [
        ({"mode": "video", "location": "https://meet.example.com/abc"}, "external_link"),
        ({"mode": "phone", "location": "+91 98765 43210"}, "phone"),
        ({"mode": "onsite", "location": "5 Example Road, Indore"}, "onsite"),
    ],
)
def test_join_methods(client, recruiter_headers, candidate_headers, body, join):
    _, application = setup(client, recruiter_headers, candidate_headers)
    assert schedule(client, recruiter_headers, application, **body).json()["join_method"] == join


@pytest.mark.parametrize(
    "body",
    [
        {"scheduled_at": "2030-01-01T10:00:00"},  # no timezone
        {"scheduled_at": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()},  # in the past
        {"duration_minutes": 5},
        {"duration_minutes": 600},
        {"mode": "phone"},  # needs a number
        {"mode": "onsite", "location": "   "},
        {"mode": "zoom"},
    ],
)
def test_invalid_interviews_are_rejected(client, recruiter_headers, candidate_headers, body):
    _, application = setup(client, recruiter_headers, candidate_headers)
    assert schedule(client, recruiter_headers, application, **body).status_code == 422


def test_a_recruiter_cannot_double_book_themselves(client, recruiter_headers, candidate_headers, other_candidate_headers):
    job, first = setup(client, recruiter_headers, candidate_headers)
    upload_resume(client, other_candidate_headers)
    second = apply_to(client, other_candidate_headers, job["id"])
    assert schedule(client, recruiter_headers, first, scheduled_at=when(48)).status_code == 201
    clash = schedule(client, recruiter_headers, second, scheduled_at=when(48, 30))  # inside the 45 minutes
    assert clash.status_code == 409 and "overlaps" in clash.json()["detail"]
    assert schedule(client, recruiter_headers, second, scheduled_at=when(48, 45)).status_code == 201  # back to back is fine


def test_closed_applications_cannot_get_interviews(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    client.post(f"/api/applications/{application['id']}/withdraw", headers=candidate_headers)
    assert schedule(client, recruiter_headers, application).status_code == 409


def test_access_control(client, recruiter_headers, other_recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    other = other_recruiter_headers
    assert schedule(client, other, application).status_code == 404
    assert client.get(f"{R}/applications/{application['id']}/interviews", headers=other).status_code == 404
    assert client.patch(f"{R}/interviews/{interview['id']}", headers=other, json={"status": "cancelled"}).status_code == 404
    assert client.get(f"{R}/interviews", headers=other).json() == []
    assert schedule(client, candidate_headers, application).status_code == 403
    assert client.get(f"{R}/interviews", headers=candidate_headers).status_code == 403
    assert client.get(f"{R}/interviews").status_code == 401


# --------------------------------------------------------------------- changes


def test_rescheduling_asks_the_candidate_again(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    client.post(f"{C}/interviews/{interview['id']}/respond", headers=candidate_headers, json={"response": "confirmed"})
    assert client.get(f"{R}/applications/{application['id']}/interviews", headers=recruiter_headers).json()[0]["candidate_response"] == "confirmed"

    moved = client.patch(f"{R}/interviews/{interview['id']}", headers=recruiter_headers, json={"scheduled_at": when(72)})
    assert moved.status_code == 200 and moved.json()["candidate_response"] == "pending"

    notes_only = client.patch(f"{R}/interviews/{interview['id']}", headers=recruiter_headers, json={"notes": "updated"})
    assert notes_only.status_code == 200


def test_cancel_and_complete_are_final(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    a = schedule(client, recruiter_headers, application, scheduled_at=when(48)).json()
    b = schedule(client, recruiter_headers, application, scheduled_at=when(96)).json()
    assert client.patch(f"{R}/interviews/{a['id']}", headers=recruiter_headers, json={"status": "cancelled"}).json()["status"] == "cancelled"
    assert client.patch(f"{R}/interviews/{b['id']}", headers=recruiter_headers, json={"status": "completed"}).json()["status"] == "completed"
    for i in (a, b):
        assert client.patch(f"{R}/interviews/{i['id']}", headers=recruiter_headers, json={"notes": "x"}).status_code == 409
    assert client.patch(f"{R}/interviews/{a['id']}", headers=recruiter_headers, json={"status": "scheduled"}).status_code == 422
    assert client.get(f"{R}/interviews", headers=recruiter_headers).json() == []  # only open ones by default


def test_patch_validates_mode_and_location(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    assert client.patch(f"{R}/interviews/{interview['id']}", headers=recruiter_headers, json={"mode": "phone"}).status_code == 422
    ok = client.patch(f"{R}/interviews/{interview['id']}", headers=recruiter_headers, json={"mode": "phone", "location": "+1 555 0100"})
    assert ok.status_code == 200 and ok.json()["join_method"] == "phone"


# --------------------------------------------------------------------- candidate


def test_candidate_sees_invitations_but_never_internal_notes(client, recruiter_headers, candidate_headers, other_candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    schedule(client, recruiter_headers, application, notes="INTERNAL: weak on testing")
    mine = client.get(f"{C}/interviews", headers=candidate_headers).json()
    assert len(mine) == 1 and mine[0]["upcoming"] is True and mine[0]["my_response"] == "pending"
    assert "notes" not in mine[0] and "INTERNAL" not in str(mine)
    assert mine[0]["job_title"] == "Platform Engineer"
    assert client.get(f"{C}/interviews", headers=other_candidate_headers).json() == []
    assert client.get(f"{C}/interviews", headers=recruiter_headers).status_code == 403


def test_candidate_can_confirm_decline_and_change_their_mind(client, recruiter_headers, candidate_headers, other_candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    url = f"{C}/interviews/{interview['id']}/respond"
    assert client.post(url, headers=candidate_headers, json={"response": "declined"}).json()["my_response"] == "declined"
    assert client.post(url, headers=candidate_headers, json={"response": "confirmed"}).json()["my_response"] == "confirmed"
    assert client.post(url, headers=candidate_headers, json={"response": "maybe"}).status_code == 422
    assert client.post(url, headers=other_candidate_headers, json={"response": "confirmed"}).status_code == 404
    assert client.post(url, headers=recruiter_headers, json={"response": "confirmed"}).status_code == 403

    client.patch(f"{R}/interviews/{interview['id']}", headers=recruiter_headers, json={"status": "cancelled"})
    assert client.post(url, headers=candidate_headers, json={"response": "confirmed"}).status_code == 409
    assert client.get(f"{C}/interviews", headers=candidate_headers).json()[0]["upcoming"] is False


# --------------------------------------------------------------------- consent


def test_consent_notice_is_honest_about_what_is_not_offered(client, candidate_headers):
    body = client.get("/api/interviews/consent-notice", headers=candidate_headers).json()
    assert body["version"] and "not recorded and not transcribed" in body["live_av"]
    assert "not affected" in body["live_av"] and "Recording and transcription are not available" in body["not_offered"]
    assert client.get("/api/interviews/consent-notice").status_code == 401


def test_camera_microphone_consent_is_recorded_changeable_and_audited(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    url = f"{C}/interviews/{interview['id']}/consent"
    assert client.get(f"{C}/interviews", headers=candidate_headers).json()[0]["live_av_consent"] is None

    assert client.put(url, headers=candidate_headers, json={"kind": "live_av", "granted": True}).json()["live_av_consent"] is True
    assert client.put(url, headers=candidate_headers, json={"granted": False}).json()["live_av_consent"] is False  # withdrawn
    assert client.put(url, headers=candidate_headers, json={"granted": True}).json()["live_av_consent"] is True

    # The recruiter can see whether consent exists, and the history is in the activity log.
    row = client.get(f"{R}/applications/{application['id']}/interviews", headers=recruiter_headers).json()[0]
    assert row["live_av_consent"] is True
    events = [e for e in client.get(f"{R}/dashboard", headers=recruiter_headers).json()["recent_activity"] if e["action"] == "interview_consent"]
    assert [e["detail"]["granted"] for e in events][::-1] == [True, False, True]
    assert all(e["detail"]["notice_version"] for e in events)

    # Saying no never touches the application.
    client.put(url, headers=candidate_headers, json={"granted": False})
    assert client.get(f"{R}/applications/{application['id']}", headers=recruiter_headers).json()["stage"] == "applied"


@pytest.mark.parametrize("kind", ["recording", "transcription", "anything"])
def test_recording_and_transcription_consent_cannot_be_collected(client, recruiter_headers, candidate_headers, kind):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    r = client.put(f"{C}/interviews/{interview['id']}/consent", headers=candidate_headers, json={"kind": kind, "granted": True})
    assert r.status_code == 422


def test_only_the_candidate_can_give_consent(client, recruiter_headers, candidate_headers, other_candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    interview = schedule(client, recruiter_headers, application).json()
    url = f"{C}/interviews/{interview['id']}/consent"
    assert client.put(url, headers=recruiter_headers, json={"granted": True}).status_code == 403
    assert client.put(url, headers=other_candidate_headers, json={"granted": True}).status_code == 404


# --------------------------------------------------------------------- emails


def draft(client, headers, application, kind):
    return client.get(f"{R}/applications/{application['id']}/email-draft", headers=headers, params={"kind": kind})


def test_rejection_draft_needs_a_recorded_human_decision(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    client.post(f"{R}/applications/{application['id']}/screen", headers=recruiter_headers)  # a low score changes nothing
    assert draft(client, recruiter_headers, application, "rejection").status_code == 409

    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers,
                 json={"stage": "rejected", "reason": "INTERNAL: salary expectations too high"})
    r = draft(client, recruiter_headers, application, "rejection")
    assert r.status_code == 200
    body = r.json()
    assert body["to"] == "candidate@example.com" and body["requires_human_review"] is True
    assert "never sends email" in body["note"]
    assert "INTERNAL" not in str(body) and "salary" not in str(body)  # the reason stays internal
    assert "Test User" in body["body"] and "Platform Engineer" in body["subject"]


def test_shortlist_draft_needs_a_shortlist_decision(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    assert draft(client, recruiter_headers, application, "shortlist").status_code == 409
    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "shortlisted"})
    assert draft(client, recruiter_headers, application, "shortlist").status_code == 200


def test_invitation_draft_uses_the_real_interview_details(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    assert draft(client, recruiter_headers, application, "interview_invitation").status_code == 409  # nothing scheduled
    schedule(client, recruiter_headers, application, mode="phone", location="+91 98765 43210", duration_minutes=30)
    body = draft(client, recruiter_headers, application, "interview_invitation").json()
    assert "+91 98765 43210" in body["body"] and "30 minutes" in body["body"] and "UTC" in body["body"]
    assert "accessible" in body["body"]  # invites candidates to ask for adjustments


def test_email_draft_access_and_validation(client, recruiter_headers, other_recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    assert draft(client, other_recruiter_headers, application, "shortlist").status_code == 404
    assert draft(client, candidate_headers, application, "shortlist").status_code == 403
    assert draft(client, recruiter_headers, application, "offer").status_code == 422


def test_drafting_is_logged_without_content(client, recruiter_headers, candidate_headers):
    _, application = setup(client, recruiter_headers, candidate_headers)
    client.patch(f"{R}/applications/{application['id']}/stage", headers=recruiter_headers, json={"stage": "shortlisted"})
    draft(client, recruiter_headers, application, "shortlist")
    events = client.get(f"{R}/dashboard", headers=recruiter_headers).json()["recent_activity"]
    entry = next(e for e in events if e["action"] == "email_drafted")
    assert entry["detail"] == {"kind": "shortlist"}
