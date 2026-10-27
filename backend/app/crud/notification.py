"""Внутренние уведомления (FR-34). Повторная доставка события идемпотентна по (user_id, event_key)."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select, tuple_
from sqlalchemy.orm import Session

from app.core.cursor import decode_cursor, encode_cursor, filters_hash
from app.core.errors import BusinessConflict, NotFound, ValidationFailed
from app.core.utils import utcnow
from app.crud._common import unique_guard
from app.models import Notification

DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def create_notification(
    db: Session, *, user_id: uuid.UUID, household_id: uuid.UUID | None, event_key: str,
    type_: str, payload: dict[str, Any] | None = None,
) -> tuple[Notification, bool]:
    """Для worker-ов. (уведомление, created). В payload не должно быть сумм и описаний покупок."""
    existing = db.execute(
        select(Notification).where(Notification.user_id == user_id, Notification.event_key == event_key)
    ).scalar_one_or_none()
    if existing is not None:
        return existing, False
    n = Notification(id=uuid.uuid4(), user_id=user_id, household_id=household_id,
                     event_key=event_key, type=type_, payload=payload)
    try:
        with unique_guard(db, "NOTIFICATION_EXISTS", "Уведомление уже создано"):
            db.add(n)
    except BusinessConflict:
        again = db.execute(
            select(Notification).where(Notification.user_id == user_id, Notification.event_key == event_key)
        ).scalar_one_or_none()
        if again is None:
            raise
        return again, False
    return n, True


def list_notifications(
    db: Session, user_id: uuid.UUID, *, unread_only: bool = False, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[Notification], str | None, bool]:
    """GET /notifications: только свои, новые первыми."""
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    conds: list[Any] = [Notification.user_id == user_id]
    if unread_only:
        conds.append(Notification.read_at.is_(None))
    fhash = filters_hash({"unread": unread_only})
    if cursor:
        data = decode_cursor(cursor)
        if data.get("f") != fhash:
            raise ValidationFailed("Курсор не соответствует фильтрам", code="INVALID_CURSOR")
        try:
            last_c, last_id = datetime.fromisoformat(data["c"]), uuid.UUID(data["i"])
        except (KeyError, ValueError):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        conds.append(tuple_(Notification.created_at, Notification.id) < tuple_(last_c, last_id))
    rows = list(db.execute(
        select(Notification).where(*conds).order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit + 1)
    ).scalars().all())
    has_more = len(rows) > limit
    items = rows[:limit]
    nxt = encode_cursor({"c": items[-1].created_at.isoformat(), "i": str(items[-1].id), "f": fhash}) if has_more and items else None
    return items, nxt, has_more


def mark_read(db: Session, user_id: uuid.UUID, notification_id: uuid.UUID) -> None:
    """POST /notifications/{id}/read — идемпотентно; чужое уведомление = 404."""
    n = db.get(Notification, notification_id)
    if n is None or n.user_id != user_id:
        raise NotFound("Уведомление не найдено")
    if n.read_at is None:
        n.read_at = utcnow()
        db.flush()
