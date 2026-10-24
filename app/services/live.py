"""Live interview support: who may join, short-lived join tickets, ICE servers, room bookkeeping.

What this does NOT do: it never touches audio or video. Media flows directly between the two
browsers (WebRTC). The server only introduces the two people and relays small signalling messages.
Nothing is recorded or transcribed.

Limits (documented in INTERVIEW_GUIDE.md): rooms live in memory, so this works for ONE server
process. Several processes would need a shared message bus such as Redis.
"""
import base64
import hashlib
import hmac
import os
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import WebSocket
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Application, Interview, InterviewStatus, Job, Role, User
from app.services import interviews as interview_rules
from app.services.assessments import aware

TICKET_SECONDS = 60
JOIN_OPENS_BEFORE = timedelta(minutes=15)
JOIN_CLOSES_AFTER = timedelta(minutes=60)  # after the scheduled end
AUTH_TIMEOUT_SECONDS = 5
MAX_MESSAGE_BYTES = 64 * 1024
RATE_LIMIT_MESSAGES = 120  # per RATE_LIMIT_SECONDS, per connection
RATE_LIMIT_SECONDS = 10
RELAY_TYPES = {"offer", "answer", "candidate", "state", "hangup"}

DEFAULT_STUN = "stun:stun.l.google.com:19302"

# WebSocket close codes (4xxx are application-defined)
CLOSE_REPLACED = 4000
CLOSE_UNAUTHORIZED = 4401
CLOSE_FORBIDDEN = 4403
CLOSE_TIMEOUT = 4408
CLOSE_TOO_LARGE = 4413
CLOSE_RATE_LIMIT = 4429


class JoinDenied(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


@dataclass
class Participant:
    interview: Interview
    application: Application
    user: User
    role: str  # "candidate" or "interviewer"


def resolve_participant(db: Session, interview_id: int, user: User) -> Participant:
    """Only the candidate of the application or the recruiter who owns the job may take part."""
    row = db.execute(
        select(Interview, Application, Job)
        .join(Application, Interview.application_id == Application.id)
        .join(Job, Application.job_id == Job.id)
        .where(Interview.id == interview_id)
    ).first()
    if row is not None:
        interview, application, job = row
        if user.role == Role.candidate and application.candidate_id == user.id:
            return Participant(interview, application, user, "candidate")
        if user.role == Role.recruiter and job.recruiter_id == user.id:
            return Participant(interview, application, user, "interviewer")
    raise JoinDenied(404, "not_found", "Interview not found.")


def check_joinable(db: Session, p: Participant, now: datetime | None = None) -> datetime:
    """Raise JoinDenied unless this person may join right now. Returns when the room closes."""
    now = now or datetime.now(timezone.utc)
    interview = p.interview
    if interview.status != InterviewStatus.scheduled:
        raise JoinDenied(409, "interview_closed", f"This interview is {interview.status.value}.")
    if interview_rules.join_method(interview.mode, interview.location) != "platform":
        raise JoinDenied(409, "not_platform", "This interview does not use the HireSense live room.")
    start = aware(interview.scheduled_at)
    opens = start - JOIN_OPENS_BEFORE
    closes = start + timedelta(minutes=interview.duration_minutes) + JOIN_CLOSES_AFTER
    if now < opens:
        raise JoinDenied(409, "too_early", f"The room opens at {opens.strftime('%H:%M UTC on %d %B %Y')}.")
    if now > closes:
        raise JoinDenied(409, "too_late", "This interview time has passed.")
    if p.role == "candidate":
        if interview_rules.attendance_response(db, interview.id, p.user.id) == "declined":
            raise JoinDenied(409, "declined", "You declined this interview. Confirm it again to join.")
        if interview_rules.live_av_consent(db, interview.id, p.user.id) is not True:
            raise JoinDenied(
                403, "consent_required",
                "Please agree to share your camera and microphone for this interview before joining.",
            )
    return closes


# --------------------------------------------------------------------------- tickets

_used_tickets: dict[str, float] = {}


def create_ticket(p: Participant) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "typ": "interview-ticket",
        "sub": str(p.user.id),
        "iid": p.interview.id,
        "role": p.role,
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + timedelta(seconds=TICKET_SECONDS),
    }
    return jwt.encode(claims, get_settings().secret_key, algorithm="HS256")


def verify_ticket(token: str, interview_id: int) -> dict:
    try:
        claims = jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        raise JoinDenied(401, "bad_ticket", "The join ticket is invalid or has expired.") from None
    if claims.get("typ") != "interview-ticket" or claims.get("iid") != interview_id:
        raise JoinDenied(401, "bad_ticket", "The join ticket is not valid for this interview.")
    now = time.time()
    for jti in [j for j, exp in _used_tickets.items() if exp < now]:
        del _used_tickets[jti]
    if claims["jti"] in _used_tickets:  # one use only
        raise JoinDenied(401, "bad_ticket", "This join ticket was already used.")
    _used_tickets[claims["jti"]] = float(claims["exp"])
    return claims


# ----------------------------------------------------------------------- ICE servers


def turn_credentials(secret: str, user_id: int, now: float | None = None, ttl: int = 3600) -> tuple[str, str]:
    """Time-limited TURN login for coturn's `use-auth-secret` mode (the secret never leaves the server)."""
    username = f"{int((now if now is not None else time.time()) + ttl)}:{user_id}"
    digest = hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()
    return username, base64.b64encode(digest).decode()


def ice_servers(user_id: int) -> list[dict]:
    stun = [u.strip() for u in os.environ.get("STUN_URLS", DEFAULT_STUN).split(",") if u.strip()]
    servers: list[dict] = [{"urls": stun, "username": None, "credential": None}] if stun else []
    turn = [u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()]
    secret = os.environ.get("TURN_SECRET", "")
    if turn and secret:
        username, credential = turn_credentials(secret, user_id)
        servers.append({"urls": turn, "username": username, "credential": credential})
    return servers


# --------------------------------------------------------------------- message rules


def validate_message(kind: str, data: object) -> dict:
    """Only small, well-formed signalling messages are relayed. Anything else is refused."""
    if kind not in RELAY_TYPES:
        raise ValueError("Unknown message type.")
    if kind in ("offer", "answer"):
        if not isinstance(data, dict) or not isinstance(data.get("sdp"), str) or data.get("type") != kind:
            raise ValueError("Malformed session description.")
        return {"type": kind, "sdp": data["sdp"]}
    if kind == "candidate":
        if data is None:
            return {}
        if not isinstance(data, dict) or not isinstance(data.get("candidate", ""), str):
            raise ValueError("Malformed ICE candidate.")
        allowed = {k: data[k] for k in ("candidate", "sdpMid", "sdpMLineIndex", "usernameFragment") if k in data}
        return allowed
    if kind == "state":
        if not isinstance(data, dict):
            raise ValueError("Malformed state.")
        return {k: bool(data[k]) for k in ("audio", "video") if k in data}
    return {}  # hangup


class RateLimiter:
    def __init__(self, limit: int, seconds: float):
        self.limit, self.seconds, self.stamps = limit, seconds, []

    def allow(self) -> bool:
        now = time.monotonic()
        self.stamps = [t for t in self.stamps if now - t < self.seconds]
        if len(self.stamps) >= self.limit:
            return False
        self.stamps.append(now)
        return True


# ------------------------------------------------------------------------------ rooms


class RoomManager:
    """Two seats per interview: one 'candidate', one 'interviewer'. A newer connection replaces an older one."""

    def __init__(self):
        self._rooms: dict[int, dict[str, WebSocket]] = {}

    def peer(self, interview_id: int, role: str) -> WebSocket | None:
        other = "interviewer" if role == "candidate" else "candidate"
        return self._rooms.get(interview_id, {}).get(other)

    async def join(self, interview_id: int, role: str, ws: WebSocket) -> bool:
        room = self._rooms.setdefault(interview_id, {})
        old = room.get(role)
        room[role] = ws
        if old is not None and old is not ws:
            try:
                await old.close(code=CLOSE_REPLACED)
            except Exception:  # already closed
                pass
        return self.peer(interview_id, role) is not None

    def leave(self, interview_id: int, role: str, ws: WebSocket) -> bool:
        """Returns True if this connection was still the one holding the seat."""
        room = self._rooms.get(interview_id, {})
        if room.get(role) is ws:
            del room[role]
            if not room:
                self._rooms.pop(interview_id, None)
            return True
        return False


rooms = RoomManager()
