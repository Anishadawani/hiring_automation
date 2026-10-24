"""Live interview: join tickets (HTTP) and the signalling WebSocket.

Camera and microphone data never pass through this server. The two browsers connect directly
(WebRTC); this module only checks who may join and relays small setup messages.
"""
import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Callable, Literal

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import SessionLocal, get_db
from app.deps import get_current_user
from app.models import User
from app.services import live
from app.services.activity import log_activity

router = APIRouter(tags=["live interview"])


class IceServer(BaseModel):
    urls: list[str]
    username: str | None = None
    credential: str | None = None


class JoinTicketOut(BaseModel):
    ticket: str
    expires_in_seconds: int
    role: Literal["candidate", "interviewer"]
    ice_servers: list[IceServer]
    window_closes_at: datetime


def get_session_factory() -> Callable[[], Session]:
    return SessionLocal  # tests replace this so the WebSocket uses the test database


@contextmanager
def session_scope(factory: Callable[[], Session]):
    db = factory()
    try:
        yield db
    finally:
        db.close()


def _denied(exc: live.JoinDenied) -> HTTPException:
    return HTTPException(exc.status, {"code": exc.code, "message": exc.message})


@router.post("/api/interviews/{interview_id}/join-ticket", response_model=JoinTicketOut)
def join_ticket(interview_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """A one-use, 60-second ticket to open the signalling connection. Consent is checked here."""
    try:
        participant = live.resolve_participant(db, interview_id, user)
        closes = live.check_joinable(db, participant)
    except live.JoinDenied as exc:
        raise _denied(exc)
    return JoinTicketOut(
        ticket=live.create_ticket(participant),
        expires_in_seconds=live.TICKET_SECONDS,
        role=participant.role,
        ice_servers=[IceServer(**s) for s in live.ice_servers(user.id)],
        window_closes_at=closes,
    )


def _authorise(factory: Callable[[], Session], interview_id: int, user_id: int, role: str):
    """Re-check everything at connection time (consent may have been withdrawn since the ticket)."""
    with session_scope(factory) as db:
        user = db.get(User, user_id)
        if user is None or not user.is_active:
            raise live.JoinDenied(401, "bad_ticket", "Account not available.")
        participant = live.resolve_participant(db, interview_id, user)
        if participant.role != role:
            raise live.JoinDenied(401, "bad_ticket", "The join ticket does not match your role.")
        closes = live.check_joinable(db, participant)
        log_activity(
            db, user.id, "interview_joined", job_id=participant.application.job_id,
            application_id=participant.application.id, detail={"interview_id": interview_id, "role": role},
        )
        db.commit()
        return closes, participant.application.job_id, participant.application.id


def _log_left(factory: Callable[[], Session], interview_id: int, user_id: int, role: str, job_id: int, app_id: int):
    with session_scope(factory) as db:
        log_activity(
            db, user_id, "interview_left", job_id=job_id, application_id=app_id,
            detail={"interview_id": interview_id, "role": role},
        )
        db.commit()


async def _refuse(ws: WebSocket, code: int, error: str, message: str) -> None:
    try:
        await ws.send_json({"type": "error", "code": error, "message": message})
        await ws.close(code=code)
    except Exception:  # the peer already went away
        pass


@router.websocket("/ws/interviews/{interview_id}")
async def interview_socket(
    websocket: WebSocket, interview_id: int, factory: Callable[[], Session] = Depends(get_session_factory)
):
    await websocket.accept()

    # 1. The first message must be {"type": "auth", "ticket": "..."} (never put tickets in the URL).
    try:
        first = await asyncio.wait_for(websocket.receive_text(), timeout=live.AUTH_TIMEOUT_SECONDS)
        message = json.loads(first)
        if not isinstance(message, dict) or message.get("type") != "auth" or not isinstance(message.get("ticket"), str):
            raise ValueError
    except asyncio.TimeoutError:
        await _refuse(websocket, live.CLOSE_TIMEOUT, "timeout", "No ticket was received in time.")
        return
    except (WebSocketDisconnect, ValueError):
        await _refuse(websocket, live.CLOSE_UNAUTHORIZED, "bad_ticket", "Send your join ticket first.")
        return

    # 2. Verify the ticket and re-check consent, time window and membership.
    try:
        claims = live.verify_ticket(message["ticket"], interview_id)
        closes, job_id, app_id = await run_in_threadpool(
            _authorise, factory, interview_id, int(claims["sub"]), claims["role"]
        )
    except live.JoinDenied as exc:
        code = live.CLOSE_FORBIDDEN if exc.status in (403, 404, 409) else live.CLOSE_UNAUTHORIZED
        await _refuse(websocket, code, exc.code, exc.message)
        return
    role, user_id = claims["role"], int(claims["sub"])

    # 3. Take a seat in the room and tell both sides.
    peer_present = await live.rooms.join(interview_id, role, websocket)
    await websocket.send_json({"type": "joined", "role": role, "polite": role == "candidate", "peer_present": peer_present})
    peer = live.rooms.peer(interview_id, role)
    if peer is not None:
        await peer.send_json({"type": "peer-joined", "role": role})

    limiter = live.RateLimiter(live.RATE_LIMIT_MESSAGES, live.RATE_LIMIT_SECONDS)
    try:
        while True:
            text = await websocket.receive_text()
            if len(text.encode()) > live.MAX_MESSAGE_BYTES:
                await _refuse(websocket, live.CLOSE_TOO_LARGE, "too_large", "Message too large.")
                return
            if not limiter.allow():
                await _refuse(websocket, live.CLOSE_RATE_LIMIT, "rate_limited", "Too many messages.")
                return
            if datetime.now(timezone.utc) > closes:
                await _refuse(websocket, live.CLOSE_TIMEOUT, "too_late", "This interview time has passed.")
                return
            try:
                incoming = json.loads(text)
                kind = incoming["type"]
                data = live.validate_message(kind, incoming.get("data"))
            except (ValueError, KeyError, TypeError):
                await websocket.send_json({"type": "error", "code": "bad_message", "message": "Message not understood."})
                continue
            target = live.rooms.peer(interview_id, role)
            if target is not None:
                await target.send_json({"type": kind, "data": data, "from": role})
    except WebSocketDisconnect:
        pass
    finally:
        if live.rooms.leave(interview_id, role, websocket):
            other = live.rooms.peer(interview_id, role)
            if other is not None:
                try:
                    await other.send_json({"type": "peer-left", "role": role})
                except Exception:
                    pass
            await run_in_threadpool(_log_left, factory, interview_id, user_id, role, job_id, app_id)
