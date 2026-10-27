"""Серверные сеансы (архитектура 13.1): секрет в cookie, на сервере только хэш."""
from __future__ import annotations

import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.core.config import get_csrf_key
from app.core.errors import AuthenticationFailed, NotFound
from app.core.security import new_token, safe_equals, token_hash
from app.core.utils import as_utc, utcnow
from app.models import User, UserSession
from app.models.enums import UserStatus

IDLE_TTL = timedelta(hours=24)
ABSOLUTE_TTL = timedelta(days=30)


@dataclass(frozen=True)
class IssuedSession:
    session: UserSession
    secret: str  # отдаётся только в Set-Cookie, больше нигде не хранится


def create_session(db: Session, user: User, device_label: str | None = None) -> IssuedSession:
    now = utcnow()
    secret = new_token()
    session = UserSession(
        id=uuid.uuid4(),
        user_id=user.id,
        session_secret_hash=token_hash(secret),
        created_at=now,
        last_seen_at=now,
        idle_expires_at=now + IDLE_TTL,
        absolute_expires_at=now + ABSOLUTE_TTL,
        device_label=(device_label or None) and device_label[:120],
    )
    db.add(session)
    db.flush()
    return IssuedSession(session=session, secret=secret)


def get_active_session(db: Session, secret: str, *, touch: bool = True) -> tuple[UserSession, User]:
    """Проверяет срок, отзыв и статус аккаунта; продлевает неактивность, но не дальше абсолютного срока."""
    session = db.execute(
        select(UserSession).where(UserSession.session_secret_hash == token_hash(secret))
    ).scalar_one_or_none()
    now = utcnow()
    if (
        session is None
        or session.revoked_at is not None
        or as_utc(session.idle_expires_at) <= now
        or as_utc(session.absolute_expires_at) <= now
    ):
        raise AuthenticationFailed("Требуется вход")
    user = db.get(User, session.user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AuthenticationFailed("Требуется вход")
    if touch:
        session.last_seen_at = now
        session.idle_expires_at = min(now + IDLE_TTL, as_utc(session.absolute_expires_at))
    return session, user


def issue_csrf_token(db: Session, session: UserSession) -> str:
    """GET /auth/csrf: токен привязан к сеансу и детерминирован (HMAC от id сеанса и хэша секрета),
    поэтому несколько вкладок получают один и тот же токен и не сбрасывают друг друга.
    Клиент держит его только в памяти."""
    raw = hmac.new(
        get_csrf_key(), f"{session.id}:{session.session_secret_hash}".encode("utf-8"), hashlib.sha256
    ).hexdigest()
    session.csrf_secret_hash = token_hash(raw)
    db.flush()
    return raw


def verify_csrf(session: UserSession, raw: str | None) -> bool:
    if not raw or not session.csrf_secret_hash:
        return False
    return safe_equals(session.csrf_secret_hash, token_hash(raw))


def list_sessions(db: Session, user_id: uuid.UUID) -> list[UserSession]:
    now = utcnow()
    rows = db.execute(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    ).scalars().all()
    return [s for s in rows if as_utc(s.idle_expires_at) > now and as_utc(s.absolute_expires_at) > now]


def revoke_session(db: Session, user_id: uuid.UUID, session_id: uuid.UUID) -> None:
    """DELETE /sessions/{id}: только сеанс того же пользователя."""
    session = db.get(UserSession, session_id)
    if session is None or session.user_id != user_id:
        raise NotFound("Сеанс не найден")
    if session.revoked_at is None:
        session.revoked_at = utcnow()
        db.flush()


def revoke_all_sessions(db: Session, user_id: uuid.UUID, *, except_session_id: uuid.UUID | None = None) -> int:
    stmt = (
        update(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .values(revoked_at=utcnow())
    )
    if except_session_id is not None:
        stmt = stmt.where(UserSession.id != except_session_id)
    result = db.execute(stmt)
    return int(result.rowcount or 0)
