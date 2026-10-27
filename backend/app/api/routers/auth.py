"""POST /auth/* и GET /auth/csrf (архитектура 7.2)."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Request, Response
from sqlalchemy.orm import Session

from app.api.deps import (
    Auth, clear_session_cookie, get_auth, get_auth_no_csrf, get_db, origin_guard, set_session_cookie,
)
from app.core.email import send_email
from app.core.errors import AccessDenied
from app.core.security import verify_password
from app.crud import session as session_crud
from app.crud import user as user_crud
from app.crud._common import add_audit
from app.schemas.auth import (
    AcceptedOut, CsrfOut, LoginOut, PasswordIn, PasswordResetConfirmIn, PasswordResetIn, TokenIn,
)
from app.schemas.user import LoginIn, RegisterIn, SessionSummary, UserSummary

router = APIRouter(prefix="/auth", tags=["auth"], dependencies=[Depends(origin_guard)])


@router.post("/register", status_code=202, response_model=AcceptedOut, operation_id="auth_register")
def register(body: RegisterIn, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Всегда 202 и один и тот же ответ — не раскрываем, занят ли адрес."""
    user, token = user_crud.register_user(db, email=body.email, password=body.password, terms_version=body.terms_version)
    db.commit()
    if user is not None:
        tasks.add_task(send_email, "verify_email", user.email_normalized, {"token": token})
    return AcceptedOut()


@router.post("/verify-email", status_code=204, operation_id="auth_verify_email")
def verify_email(body: TokenIn, db: Session = Depends(get_db)):
    user_crud.verify_email(db, body.token)
    db.commit()
    return Response(status_code=204)


@router.post("/login", response_model=LoginOut, operation_id="auth_login")
def login(body: LoginIn, response: Response, db: Session = Depends(get_db)):
    user = user_crud.authenticate(db, body.email, body.password)
    issued = session_crud.create_session(db, user, body.device_label)
    add_audit(db, actor_id=user.id, household_id=None, action="session.login", target_type="session", target_id=issued.session.id)
    out = LoginOut(
        user=UserSummary.model_validate(user),
        session=SessionSummary(
            session_id=issued.session.id,
            idle_expires_at=issued.session.idle_expires_at,
            absolute_expires_at=issued.session.absolute_expires_at,
        ),
    )
    db.commit()
    set_session_cookie(response, issued.secret)  # секрет только в Set-Cookie, не в JSON
    return out


@router.post("/refresh", response_model=SessionSummary, operation_id="auth_refresh")
def refresh(auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    """Сеанс уже продлён в get_auth (неактивность, но не дальше абсолютного срока)."""
    out = SessionSummary(
        session_id=auth.session.id,
        idle_expires_at=auth.session.idle_expires_at,
        absolute_expires_at=auth.session.absolute_expires_at,
    )
    db.commit()
    return out


@router.post("/logout", status_code=204, operation_id="auth_logout")
def logout(response: Response, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    session_crud.revoke_session(db, auth.user.id, auth.session.id)
    add_audit(db, actor_id=auth.user.id, household_id=None, action="session.logout", target_type="session", target_id=auth.session.id)
    db.commit()
    resp = Response(status_code=204)
    clear_session_cookie(resp)
    return resp


@router.post("/logout-all", status_code=204, operation_id="auth_logout_all")
def logout_all(body: PasswordIn, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    if not verify_password(auth.user.password_hash, body.password):
        raise AccessDenied("Неверный пароль", code="INVALID_PASSWORD")
    session_crud.revoke_all_sessions(db, auth.user.id)
    add_audit(db, actor_id=auth.user.id, household_id=None, action="session.logout_all", target_type="user", target_id=auth.user.id)
    db.commit()
    resp = Response(status_code=204)
    clear_session_cookie(resp)
    return resp


@router.post("/password-reset", status_code=202, response_model=AcceptedOut, operation_id="auth_password_reset")
def password_reset(body: PasswordResetIn, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    user, token = user_crud.request_password_reset(db, body.email)
    db.commit()
    if user is not None:
        tasks.add_task(send_email, "password_reset", user.email_normalized, {"token": token})
    return AcceptedOut()


@router.post("/password-reset/confirm", status_code=204, operation_id="auth_password_reset_confirm")
def password_reset_confirm(body: PasswordResetConfirmIn, db: Session = Depends(get_db)):
    user_crud.confirm_password_reset(db, body.token, body.new_password)
    db.commit()
    return Response(status_code=204)


@router.get("/csrf", response_model=CsrfOut, operation_id="auth_csrf")
def csrf(auth: Auth = Depends(get_auth_no_csrf), db: Session = Depends(get_db)):
    token = session_crud.issue_csrf_token(db, auth.session)
    db.commit()
    return CsrfOut(csrf_token=token)
