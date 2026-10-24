"""Live interview: join rules, tickets, signalling relay, limits. No real media is involved."""
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone

import pytest
from starlette.websockets import WebSocketDisconnect

import itertools

from app.database import get_db
from app.main import app
from app.models import Interview
from app.routers.live_interview import get_session_factory
from app.services import live
from tests.conftest import apply_to, create_job, upload_resume

R = "/api/recruiter"
C = "/api/candidate"
OFFER = {"type": "offer", "sdp": "v=0\r\no=- 1 2 IN IP4 127.0.0.1\r\n"}
ANSWER = {"type": "answer", "sdp": "v=0\r\no=- 3 4 IN IP4 127.0.0.1\r\n"}


def at(hours=0, minutes=0):
    return (datetime.now(timezone.utc) + timedelta(hours=hours, minutes=minutes)).replace(microsecond=0).isoformat()


@pytest.fixture(autouse=True)
def socket_db(db_session):
    """Make the WebSocket use the same in-memory test database as the HTTP routes."""
    app.dependency_overrides[get_session_factory] = lambda: (lambda: db_session)


_slot = itertools.count(1)


def room(client, recruiter_headers, candidate_headers, starts_in=timedelta(minutes=5), consent=True, **body):
    """A platform video interview. It is created far in the future (so recruiters never clash with
    themselves) and then moved to `starts_in` from now directly in the test database."""
    job = create_job(client, recruiter_headers)
    upload_resume(client, candidate_headers)
    application = apply_to(client, candidate_headers, job["id"])
    payload = {"scheduled_at": at(hours=100 + 2 * next(_slot)), "duration_minutes": 30, "mode": "video", **body}
    interview = client.post(f"{R}/applications/{application['id']}/interviews", headers=recruiter_headers, json=payload).json()
    session = next(app.dependency_overrides[get_db]())
    session.get(Interview, interview["id"]).scheduled_at = datetime.now(timezone.utc) + starts_in
    session.commit()
    if consent:
        client.put(f"{C}/interviews/{interview['id']}/consent", headers=candidate_headers, json={"granted": True})
    return interview


def ticket(client, headers, interview):
    r = client.post(f"/api/interviews/{interview['id']}/join-ticket", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["ticket"]


def ws_url(interview):
    return f"/ws/interviews/{interview['id']}"


def expect_refused(ws, code):
    message = ws.receive_json()
    assert message["type"] == "error"
    with pytest.raises(WebSocketDisconnect) as closed:
        ws.receive_json()
    assert closed.value.code == code
    return message


# ------------------------------------------------------------------------ tickets


def test_candidate_needs_consent_but_the_interviewer_does_not(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers, consent=False)
    url = f"/api/interviews/{interview['id']}/join-ticket"
    refused = client.post(url, headers=candidate_headers)
    assert refused.status_code == 403 and refused.json()["detail"]["code"] == "consent_required"

    assert client.post(url, headers=recruiter_headers).json()["role"] == "interviewer"
    client.put(f"{C}/interviews/{interview['id']}/consent", headers=candidate_headers, json={"granted": True})
    ok = client.post(url, headers=candidate_headers).json()
    assert ok["role"] == "candidate" and ok["expires_in_seconds"] == 60 and ok["ticket"]
    assert ok["ice_servers"][0]["urls"] and ok["window_closes_at"]

    # Withdrawing consent closes the door again.
    client.put(f"{C}/interviews/{interview['id']}/consent", headers=candidate_headers, json={"granted": False})
    assert client.post(url, headers=candidate_headers).status_code == 403


def test_only_the_two_participants_may_get_tickets(client, recruiter_headers, other_recruiter_headers, candidate_headers, other_candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    url = f"/api/interviews/{interview['id']}/join-ticket"
    assert client.post(url, headers=other_recruiter_headers).status_code == 404
    assert client.post(url, headers=other_candidate_headers).status_code == 404
    assert client.post(url).status_code == 401
    assert client.post("/api/interviews/99999/join-ticket", headers=candidate_headers).status_code == 404


def test_join_window_and_interview_state(client, recruiter_headers, candidate_headers, db_session):
    url = lambda i: f"/api/interviews/{i['id']}/join-ticket"
    early = room(client, recruiter_headers, candidate_headers, starts_in=timedelta(hours=48))
    r = client.post(url(early), headers=recruiter_headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "too_early"

    late = room(client, recruiter_headers, candidate_headers, starts_in=-timedelta(hours=5))
    assert client.post(url(late), headers=recruiter_headers).json()["detail"]["code"] == "too_late"

    cancelled = room(client, recruiter_headers, candidate_headers)
    client.patch(f"{R}/interviews/{cancelled['id']}", headers=recruiter_headers, json={"status": "cancelled"})
    assert client.post(url(cancelled), headers=recruiter_headers).json()["detail"]["code"] == "interview_closed"


def test_external_and_declined_interviews_cannot_use_the_live_room(client, recruiter_headers, candidate_headers):
    external = room(client, recruiter_headers, candidate_headers, location="https://meet.example.com/x")
    r = client.post(f"/api/interviews/{external['id']}/join-ticket", headers=recruiter_headers)
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_platform"

    declined = room(client, recruiter_headers, candidate_headers)
    client.post(f"{C}/interviews/{declined['id']}/respond", headers=candidate_headers, json={"response": "declined"})
    r = client.post(f"/api/interviews/{declined['id']}/join-ticket", headers=candidate_headers)
    assert r.json()["detail"]["code"] == "declined"


# ---------------------------------------------------------------------- the call


def test_two_people_exchange_setup_messages(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    with client.websocket_connect(ws_url(interview)) as rec:
        rec.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        assert rec.receive_json() == {"type": "joined", "role": "interviewer", "polite": False, "peer_present": False}
        with client.websocket_connect(ws_url(interview)) as cand:
            cand.send_json({"type": "auth", "ticket": ticket(client, candidate_headers, interview)})
            assert cand.receive_json() == {"type": "joined", "role": "candidate", "polite": True, "peer_present": True}
            assert rec.receive_json() == {"type": "peer-joined", "role": "candidate"}

            rec.send_json({"type": "offer", "data": OFFER})
            assert cand.receive_json() == {"type": "offer", "data": OFFER, "from": "interviewer"}
            cand.send_json({"type": "answer", "data": ANSWER})
            assert rec.receive_json() == {"type": "answer", "data": ANSWER, "from": "candidate"}

            cand.send_json({"type": "candidate", "data": {"candidate": "candidate:1 1 UDP 1 10.0.0.1 5000 typ host", "sdpMid": "0", "sdpMLineIndex": 0, "evil": "dropped"}})
            relayed = rec.receive_json()
            assert relayed["type"] == "candidate" and "evil" not in relayed["data"] and relayed["data"]["sdpMid"] == "0"

            cand.send_json({"type": "state", "data": {"audio": False, "video": True, "junk": 1}})
            assert rec.receive_json() == {"type": "state", "data": {"audio": False, "video": True}, "from": "candidate"}

            rec.send_json({"type": "hangup"})
            assert cand.receive_json() == {"type": "hangup", "data": {}, "from": "interviewer"}
        assert rec.receive_json() == {"type": "peer-left", "role": "candidate"}


def test_join_and_leave_are_logged_without_any_content(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    with client.websocket_connect(ws_url(interview)) as rec:
        rec.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        rec.receive_json()
        rec.send_json({"type": "state", "data": {"audio": True}})
    events = client.get(f"{R}/dashboard", headers=recruiter_headers).json()["recent_activity"]
    actions = [e for e in events if e["action"] in ("interview_joined", "interview_left")]
    assert {e["action"] for e in actions} == {"interview_joined", "interview_left"}
    assert all(e["detail"] == {"interview_id": interview["id"], "role": "interviewer"} for e in actions)


def test_a_newer_connection_replaces_an_older_one(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    with client.websocket_connect(ws_url(interview)) as first:
        first.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        first.receive_json()
        with client.websocket_connect(ws_url(interview)) as second:  # e.g. the page was refreshed
            second.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
            assert second.receive_json()["type"] == "joined"
            with pytest.raises(WebSocketDisconnect) as closed:
                first.receive_json()
            assert closed.value.code == live.CLOSE_REPLACED


# ------------------------------------------------------------------- refusals


def test_bad_tickets_are_refused(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    other = room(client, recruiter_headers, candidate_headers)

    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": "not-a-ticket"})
        assert expect_refused(ws, live.CLOSE_UNAUTHORIZED)["code"] == "bad_ticket"

    with client.websocket_connect(ws_url(interview)) as ws:  # a ticket for a different interview
        ws.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, other)})
        expect_refused(ws, live.CLOSE_UNAUTHORIZED)

    used = ticket(client, recruiter_headers, interview)
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": used})
        assert ws.receive_json()["type"] == "joined"
    with client.websocket_connect(ws_url(interview)) as ws:  # one use only
        ws.send_json({"type": "auth", "ticket": used})
        assert expect_refused(ws, live.CLOSE_UNAUTHORIZED)["code"] == "bad_ticket"

    with client.websocket_connect(ws_url(interview)) as ws:  # first message must be auth
        ws.send_json({"type": "offer", "data": OFFER})
        expect_refused(ws, live.CLOSE_UNAUTHORIZED)


def test_expired_tickets_are_refused(client, recruiter_headers, candidate_headers, monkeypatch):
    interview = room(client, recruiter_headers, candidate_headers)
    monkeypatch.setattr(live, "TICKET_SECONDS", -10)
    stale = ticket(client, recruiter_headers, interview)
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": stale})
        expect_refused(ws, live.CLOSE_UNAUTHORIZED)


def test_silent_connections_time_out(client, recruiter_headers, candidate_headers, monkeypatch):
    interview = room(client, recruiter_headers, candidate_headers)
    monkeypatch.setattr(live, "AUTH_TIMEOUT_SECONDS", 0.2)
    with client.websocket_connect(ws_url(interview)) as ws:
        assert expect_refused(ws, live.CLOSE_TIMEOUT)["code"] == "timeout"


def test_consent_withdrawn_after_the_ticket_is_still_honoured(client, recruiter_headers, candidate_headers):
    interview = room(client, recruiter_headers, candidate_headers)
    t = ticket(client, candidate_headers, interview)
    client.put(f"{C}/interviews/{interview['id']}/consent", headers=candidate_headers, json={"granted": False})
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": t})
        assert expect_refused(ws, live.CLOSE_FORBIDDEN)["code"] == "consent_required"


def test_nothing_but_setup_messages_is_relayed(client, recruiter_headers, candidate_headers):
    assert live.RELAY_TYPES == {"offer", "answer", "candidate", "state", "hangup"}  # no media, no recording
    interview = room(client, recruiter_headers, candidate_headers)
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        ws.receive_json()
        for bad in (
            {"type": "record", "data": {}},
            {"type": "offer", "data": {"type": "answer", "sdp": "x"}},
            {"type": "offer", "data": "nonsense"},
            {"type": "candidate", "data": {"candidate": 5}},
            {"data": {}},
        ):
            ws.send_json(bad)
            assert ws.receive_json()["code"] == "bad_message"
        ws.send_text("not json at all")
        assert ws.receive_json()["code"] == "bad_message"
        ws.send_json({"type": "state", "data": {"audio": True}})  # the connection is still fine
        ws.send_json({"type": "hangup"})


def test_oversized_and_flooding_messages_close_the_connection(client, recruiter_headers, candidate_headers, monkeypatch):
    interview = room(client, recruiter_headers, candidate_headers)
    monkeypatch.setattr(live, "MAX_MESSAGE_BYTES", 200)
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        ws.receive_json()
        ws.send_json({"type": "offer", "data": {"type": "offer", "sdp": "x" * 500}})
        assert expect_refused(ws, live.CLOSE_TOO_LARGE)["code"] == "too_large"

    monkeypatch.setattr(live, "MAX_MESSAGE_BYTES", 64 * 1024)
    monkeypatch.setattr(live, "RATE_LIMIT_MESSAGES", 3)
    with client.websocket_connect(ws_url(interview)) as ws:
        ws.send_json({"type": "auth", "ticket": ticket(client, recruiter_headers, interview)})
        ws.receive_json()
        for _ in range(3):
            ws.send_json({"type": "state", "data": {"audio": True}})
        ws.send_json({"type": "state", "data": {"audio": True}})
        assert expect_refused(ws, live.CLOSE_RATE_LIMIT)["code"] == "rate_limited"


# ------------------------------------------------------------------ ICE and unit


def test_turn_credentials_are_time_limited_and_verifiable():
    username, credential = live.turn_credentials("s3cret", 42, now=1_000_000, ttl=3600)
    assert username == "1003600:42"
    expected = base64.b64encode(hmac.new(b"s3cret", username.encode(), hashlib.sha1).digest()).decode()
    assert credential == expected


def test_ice_servers_come_from_configuration(monkeypatch):
    monkeypatch.delenv("STUN_URLS", raising=False)
    monkeypatch.delenv("TURN_URLS", raising=False)
    monkeypatch.delenv("TURN_SECRET", raising=False)
    default = live.ice_servers(7)
    assert default == [{"urls": [live.DEFAULT_STUN], "username": None, "credential": None}]

    monkeypatch.setenv("STUN_URLS", "")
    assert live.ice_servers(7) == []  # a deployment can opt out of third-party STUN

    monkeypatch.setenv("STUN_URLS", "stun:stun.internal.example:3478")
    monkeypatch.setenv("TURN_URLS", "turn:turn.internal.example:3478, turns:turn.internal.example:5349")
    monkeypatch.setenv("TURN_SECRET", "s3cret")
    servers = live.ice_servers(7)
    assert servers[0]["urls"] == ["stun:stun.internal.example:3478"]
    assert servers[1]["urls"] == ["turn:turn.internal.example:3478", "turns:turn.internal.example:5349"]
    assert servers[1]["username"].endswith(":7") and servers[1]["credential"]
    assert "s3cret" not in str(servers)  # the shared secret itself is never sent to browsers
