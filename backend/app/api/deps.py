
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Iterator

from fastapi import Depends, Header, Request, Response
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import cookie_secure, is_local, public_origin, session_cookie_name
from app.core.context import RequestContext
from app.core.database import engine
from app.core.errors import AccessDenied, AuthenticationFailed, PreconditionRequired, ValidationFailed
from app.crud._common import build_context
from app.crud.session import ABSOLUTE_TTL, get_active_session, verify_csrf
from app.models import User, UserSession


_SessionFactory = sessionmaker(bind=engine, autoflush=True, expire_on_commit=False)

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def get_db() -> Iterator[Session]:
    db = _SessionFactory()
    try:
        yield db
    finally:
        db.close()


def request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def check_origin(request: Request) -> None:

    allowed = public_origin()
    if allowed is None:
        if is_local():
            return
        raise AccessDenied("PUBLIC_ORIGIN не настроен", code="ORIGIN_NOT_CONFIGURED")
    origin = request.headers.get("origin")
    if origin != allowed:
        raise AccessDenied("Недопустимый источник запроса", code="BAD_ORIGIN")


def origin_guard(request: Request) -> None:
    """Для публичных изменяющих endpoints (register, login, reset...)."""
    if request.method in MUTATING:
        check_origin(request)



@dataclass
class Auth:
    user: User
    session: UserSession


def get_auth(request: Request, db: Session = Depends(get_db)) -> Auth:
    """Чтение: достаточно действующего сеанса. Изменяющие методы дополнительно проверяют Origin и CSRF."""
    secret = request.cookies.get(session_cookie_name())
    if not secret:
        raise AuthenticationFailed("Требуется вход")
    session, user = get_active_session(db, secret)
    auth = Auth(user=user, session=session)
    if request.method in MUTATING:
        check_origin(request)
        token = request.headers.get("x-csrf-token")
        if not verify_csrf(session, token):
            raise AccessDenied("Недействительный CSRF-токен", code="BAD_CSRF")
    return auth


def get_auth_no_csrf(request: Request, db: Session = Depends(get_db)) -> Auth:

    secret = request.cookies.get(session_cookie_name())
    if not secret:
        raise AuthenticationFailed("Требуется вход")
    session, user = get_active_session(db, secret)
    return Auth(user=user, session=session)


def get_household_ctx(
    h: uuid.UUID, request: Request, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)
) -> RequestContext:

    return build_context(db, auth.user.id, h, request_id=request_id(request))


def set_session_cookie(response: Response, secret: str) -> None:
    response.set_cookie(
        key=session_cookie_name(),
        value=secret,
        max_age=int(ABSOLUTE_TTL.total_seconds()),
        httponly=True,
        secure=cookie_secure(),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(key=session_cookie_name(), path="/", secure=cookie_secure(), httponly=True, samesite="lax")


def parse_version(raw: str | None) -> int | None:

    if raw is None:
        return None
    value = raw.strip()
    if value.startswith("W/"):
        value = value[2:]
    value = value.strip('"')
    try:
        number = int(value)
    except ValueError:
        raise ValidationFailed("Некорректный заголовок If-Match", code="INVALID_IF_MATCH")
    if number < 1:
        raise ValidationFailed("Некорректный заголовок If-Match", code="INVALID_IF_MATCH")
    return number


def if_match(if_match: str | None = Header(default=None)) -> int | None:
    return parse_version(if_match)


def require_if_match(if_match: str | None = Header(default=None)) -> int:
    version = parse_version(if_match)
    if version is None:
        raise PreconditionRequired("Необходимо передать версию записи (If-Match)")
    return version


def set_etag(response: Response, version: int) -> None:
    response.headers["ETag"] = f'"{int(version)}"'
