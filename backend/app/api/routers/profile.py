"""Профиль, сеансы, согласия, уведомления, удаление аккаунта (п. 7.2, 7.7, 7.8)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Auth, clear_session_cookie, get_auth, get_db, origin_guard, require_if_match, set_etag
from app.core.email import send_email
from app.crud import consent as consent_crud
from app.crud import notification as notif_crud
from app.crud import session as session_crud
from app.crud import user as user_crud
from app.crud._common import get_active_membership
from app.schemas.auth import AcceptedOut, EmailChangeIn, PasswordIn, TokenIn
from app.schemas.common import Page
from app.schemas.insights import ConsentOut, ConsentSetIn, NotificationOut
from app.schemas.user import MembershipOut, ProfileOut, ProfilePatch, SessionListItem

router = APIRouter(tags=["profile"])


def _profile(db: Session, user) -> ProfileOut:
    member = get_active_membership(db, user.id)
    return ProfileOut(
        id=user.id, email=user.email_normalized, display_name=user.display_name, locale=user.locale,
        preferences=user.notification_preferences or {}, version=int(user.version),
        membership=MembershipOut.model_validate(member) if member else None,
    )


@router.get("/profile", response_model=ProfileOut, operation_id="profile_get")
def get_profile(response: Response, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    out = _profile(db, auth.user)
    db.commit()  # фиксирует продление сеанса
    set_etag(response, out.version)
    return out


@router.patch("/profile", response_model=ProfileOut, operation_id="profile_patch")
def patch_profile(
    body: ProfilePatch, response: Response, version: int = Depends(require_if_match),
    auth: Auth = Depends(get_auth), db: Session = Depends(get_db),
):
    user = user_crud.update_profile(db, auth.user.id, body, version)
    out = _profile(db, user)
    db.commit()
    set_etag(response, out.version)
    return out


@router.post("/profile/email-change", status_code=202, response_model=AcceptedOut, operation_id="profile_email_change")
def email_change(body: EmailChangeIn, tasks: BackgroundTasks, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    token = user_crud.request_email_change(db, auth.user.id, body.new_email, body.password)
    db.commit()
    if token is not None:
        tasks.add_task(send_email, "email_change", body.new_email.strip().lower(), {"token": token})
    return AcceptedOut()


@router.post(
    "/profile/email-change/confirm", status_code=204, operation_id="profile_email_change_confirm",
    dependencies=[Depends(origin_guard)],
)
def email_change_confirm(body: TokenIn, db: Session = Depends(get_db)):
    user_crud.confirm_email_change(db, body.token)
    db.commit()
    return Response(status_code=204)


@router.post("/profile/deletion", status_code=202, response_model=AcceptedOut, operation_id="profile_deletion")
def request_deletion(body: PasswordIn, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    """Сразу блокирует вход и отзывает сеансы; обезличивание выполнит worker (purge_user)."""
    user_crud.request_account_deletion(db, auth.user.id, body.password)
    db.commit()
    resp = Response(content=AcceptedOut().model_dump_json(), status_code=202, media_type="application/json")
    clear_session_cookie(resp)
    return resp


# ------------------------------------------------------------------ сеансы
@router.get("/sessions", response_model=list[SessionListItem], operation_id="sessions_list")
def list_sessions(auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    rows = session_crud.list_sessions(db, auth.user.id)
    db.commit()
    return [
        SessionListItem(id=s.id, device_label=s.device_label, created_at=s.created_at,
                        last_seen_at=s.last_seen_at, current=(s.id == auth.session.id))
        for s in rows
    ]


@router.delete("/sessions/{session_id}", status_code=204, operation_id="sessions_revoke")
def revoke_session(session_id: uuid.UUID, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    session_crud.revoke_session(db, auth.user.id, session_id)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ согласия
@router.get("/consents", response_model=list[ConsentOut], operation_id="consents_list")
def list_consents(auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    out = consent_crud.list_consents(db, auth.user.id)
    db.commit()
    return out


@router.put("/consents/{purpose}", response_model=ConsentOut, operation_id="consents_set")
def set_consent(purpose: str, body: ConsentSetIn, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    out = consent_crud.set_consent(db, auth.user.id, purpose, body.enabled, body.text_version)
    db.commit()
    return out


# ------------------------------------------------------------------ уведомления
@router.get("/notifications", response_model=Page[NotificationOut], operation_id="notifications_list")
def list_notifications(
    cursor: str | None = None, unread_only: bool = False, limit: int = Query(50, ge=1, le=100),
    auth: Auth = Depends(get_auth), db: Session = Depends(get_db),
):
    items, next_cursor, has_more = notif_crud.list_notifications(
        db, auth.user.id, unread_only=unread_only, cursor=cursor, limit=limit
    )
    out = Page[NotificationOut](
        items=[NotificationOut.model_validate(n) for n in items], next_cursor=next_cursor, has_more=has_more
    )
    db.commit()
    return out


@router.post("/notifications/{notification_id}/read", status_code=204, operation_id="notifications_read")
def read_notification(notification_id: uuid.UUID, auth: Auth = Depends(get_auth), db: Session = Depends(get_db)):
    notif_crud.mark_read(db, auth.user.id, notification_id)
    db.commit()
    return Response(status_code=204)
