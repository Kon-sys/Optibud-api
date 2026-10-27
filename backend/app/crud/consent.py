"""Согласия (DR-02, BR-12). Каждое включение/отзыв — отдельное событие."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.errors import ValidationFailed, field_error
from app.core.utils import utcnow
from app.crud._common import add_audit, add_outbox
from app.models import Consent, HouseholdMember
from app.models.enums import ConsentPurpose, MemberStatus
from app.schemas.insights import ConsentOut


def _active_consent(db: Session, user_id: uuid.UUID, purpose: str) -> Consent | None:
    return db.execute(
        select(Consent)
        .where(Consent.user_id == user_id, Consent.purpose == purpose, Consent.revoked_at.is_(None))
        .order_by(Consent.granted_at.desc())
    ).scalars().first()


def list_consents(db: Session, user_id: uuid.UUID) -> list[ConsentOut]:
    """GET /consents: по одной записи на каждое назначение."""
    result: list[ConsentOut] = []
    for purpose in ConsentPurpose:
        active = _active_consent(db, user_id, purpose.value)
        if active is not None:
            result.append(ConsentOut(purpose=purpose.value, enabled=True, text_version=active.text_version,
                                     granted_at=active.granted_at, revoked_at=None))
            continue
        last = db.execute(
            select(Consent).where(Consent.user_id == user_id, Consent.purpose == purpose.value)
            .order_by(Consent.granted_at.desc())
        ).scalars().first()
        result.append(ConsentOut(
            purpose=purpose.value, enabled=False,
            text_version=last.text_version if last else None,
            granted_at=last.granted_at if last else None,
            revoked_at=last.revoked_at if last else None,
        ))
    return result


def set_consent(db: Session, user_id: uuid.UUID, purpose: str, enabled: bool, text_version: str) -> ConsentOut:
    """PUT /consents/{purpose}. Повторный вызов идемпотентен; отзыв действует сразу."""
    if purpose not in {p.value for p in ConsentPurpose}:
        raise ValidationFailed(field_errors=[field_error("purpose", "Неизвестное назначение согласия")])
    active = _active_consent(db, user_id, purpose)
    changed = False
    if enabled and active is None:
        db.add(Consent(id=uuid.uuid4(), user_id=user_id, purpose=purpose, text_version=text_version, granted_at=utcnow()))
        changed = True
    elif enabled and active is not None and active.text_version != text_version:
        active.revoked_at = utcnow()  # новая версия текста = новое событие
        db.add(Consent(id=uuid.uuid4(), user_id=user_id, purpose=purpose, text_version=text_version, granted_at=utcnow()))
        changed = True
    elif not enabled and active is not None:
        active.revoked_at = utcnow()
        changed = True
    db.flush()
    if changed:
        add_audit(db, actor_id=user_id, household_id=None, action="consent.changed", target_type="consent",
                  target_id=f"{user_id}:{purpose}", details={"enabled": enabled})
        add_outbox(db, event_type="ConsentChanged", aggregate_id=user_id, household_id=None,
                   payload={"user_id": str(user_id), "purpose": purpose, "enabled": enabled})
    return next(c for c in list_consents(db, user_id) if c.purpose == purpose)


def effective_cross_household_consent(db: Session, household_id: uuid.UUID) -> bool:
    """BR-12: семья участвует в общей аналитике, только если ВСЕ активные участники согласны.
    Новый участник без согласия автоматически приостанавливает участие семьи."""
    user_ids = db.execute(
        select(HouseholdMember.user_id).where(
            HouseholdMember.household_id == household_id, HouseholdMember.status == MemberStatus.ACTIVE.value
        )
    ).scalars().all()
    if not user_ids:
        return False
    return all(
        _active_consent(db, uid, ConsentPurpose.CROSS_HOUSEHOLD_ANALYTICS.value) is not None for uid in user_ids
    )
