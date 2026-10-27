
from __future__ import annotations

import uuid
from contextlib import contextmanager
from typing import Any, Iterator

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import (
    AccessDenied,
    BusinessConflict,
    NotFound,
    PreconditionRequired,
    VersionConflict,
)
from app.models import AuditEvent, ChangeLog, Household, HouseholdMember, OutboxEvent
from app.models.enums import HouseholdStatus, MemberRole, MemberStatus


# --------------------------------------------------------------------------- #
# Авторизация
# --------------------------------------------------------------------------- #
def get_active_membership(db: Session, user_id: uuid.UUID) -> HouseholdMember | None:
    return db.execute(
        select(HouseholdMember).where(
            HouseholdMember.user_id == user_id, HouseholdMember.status == MemberStatus.ACTIVE.value
        )
    ).scalar_one_or_none()


def build_context(
    db: Session, user_id: uuid.UUID, requested_household_id: uuid.UUID | None = None, request_id: str | None = None
) -> RequestContext:
    """Контекст из активного членства. Чужой household_id -> 404 (существование не раскрываем)."""
    member = get_active_membership(db, user_id)
    if member is None or (requested_household_id is not None and member.household_id != requested_household_id):
        raise NotFound("Семья не найдена")
    return RequestContext(user_id=user_id, household_id=member.household_id, role=member.role, request_id=request_id)


def authorize(
    db: Session, ctx: RequestContext, *, lock: bool = False, require_owner: bool = False
) -> tuple[Household, HouseholdMember]:
    """Проверяет активное членство и (опционально) роль владельца.

    lock=True блокирует строку семьи FOR UPDATE и повторно проверяет права
    в том же порядке блокировок, что и исключение участника (п. 5.4): это
    закрывает гонку с исключением. Любая запись должна вызывать с lock=True.
    """
    stmt = select(Household).where(Household.id == ctx.household_id)
    if lock:
        stmt = stmt.with_for_update().execution_options(populate_existing=True)
    household = db.execute(stmt).scalar_one_or_none()
    if household is None or household.status != HouseholdStatus.ACTIVE.value:
        raise NotFound("Семья не найдена")

    member = db.execute(
        select(HouseholdMember).where(
            HouseholdMember.household_id == household.id,
            HouseholdMember.user_id == ctx.user_id,
            HouseholdMember.status == MemberStatus.ACTIVE.value,
        )
    ).scalar_one_or_none()
    if member is None:
        raise NotFound("Семья не найдена")
    if require_owner and member.role != MemberRole.OWNER.value:
        raise AccessDenied("Действие доступно только владельцу семьи")
    return household, member


# --------------------------------------------------------------------------- #
# Оптимистическая блокировка
# --------------------------------------------------------------------------- #
def require_version(expected: int | None) -> int:
    """Нет If-Match / base_version -> 428."""
    if expected is None:
        raise PreconditionRequired("Необходимо передать версию записи (If-Match)")
    return expected


def ensure_version(current: int, expected: int, current_record: Any | None = None) -> None:
    if current != expected:
        raise VersionConflict(current_version=current, current_record=current_record)


# --------------------------------------------------------------------------- #
# Журналы: change_log, audit, outbox
# --------------------------------------------------------------------------- #
def add_audit(
    db: Session,
    *,
    actor_id: uuid.UUID | None,
    household_id: uuid.UUID | None,
    action: str,
    target_type: str,
    target_id: uuid.UUID | str,
    details: dict[str, Any] | None = None,
    result: str = "success",
) -> AuditEvent:
    event = AuditEvent(
        id=uuid.uuid4(),
        actor_id=actor_id,
        household_id=household_id,
        action=action,
        target_object=f"{target_type}:{target_id}",
        details=details,
        result=result,
    )
    db.add(event)
    return event


def add_outbox(
    db: Session,
    *,
    event_type: str,
    aggregate_id: uuid.UUID,
    household_id: uuid.UUID | None,
    payload: dict[str, Any],
    correlation_id: uuid.UUID | None = None,
) -> OutboxEvent:
    """Событие пишется в той же транзакции, что и изменение (п. 9.1).
    В payload нельзя класть описание покупок, email и секреты."""
    event = OutboxEvent(
        id=uuid.uuid4(),
        event_type=event_type,
        event_version=1,
        aggregate_id=aggregate_id,
        household_id=household_id,
        correlation_id=correlation_id,
        payload=payload,
    )
    db.add(event)
    return event


def record_change(
    db: Session,
    household: Household,
    *,
    actor_id: uuid.UUID | None,
    entity_type: str,
    entity_id: uuid.UUID,
    action: str,
    entity_version: int,
    payload: dict[str, Any] | None,
    event_type: str,
    audit_action: str | None = None,
    audit_details: dict[str, Any] | None = None,
    correlation_id: uuid.UUID | None = None,
) -> int:
    """Шаг 5–6 транзакционной границы: номер изменения семьи, change_log,
    audit_event и outbox_event. household ДОЛЖЕН быть заблокирован (authorize(lock=True)).
    Возвращает присвоенный seq."""
    household.change_seq = int(household.change_seq) + 1
    household.data_version = int(household.data_version) + 1
    seq = household.change_seq

    db.add(
        ChangeLog(
            id=uuid.uuid4(),
            household_id=household.id,
            seq=seq,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            entity_version=entity_version,
            payload=payload,
        )
    )
    add_audit(
        db,
        actor_id=actor_id,
        household_id=household.id,
        action=audit_action or f"{entity_type}.{action}",
        target_type=entity_type,
        target_id=entity_id,
        details=audit_details,
    )
    add_outbox(
        db,
        event_type=event_type,
        aggregate_id=entity_id,
        household_id=household.id,
        payload={
            "household_id": str(household.id),
            "entity_type": entity_type,
            "entity_id": str(entity_id),
            "version": entity_version,
            "data_version": int(household.data_version),
        },
        correlation_id=correlation_id,
    )
    return seq


@contextmanager
def unique_guard(db: Session, code: str, message: str) -> Iterator[None]:
    """Выполняет блок и flush в SAVEPOINT. Нарушение уникальности/ограничения превращается
    в BusinessConflict, а внешняя транзакция остаётся пригодной для продолжения.

    ВАЖНО: объекты, которые могут нарушить ограничение, нужно добавлять (db.add) ВНУТРИ блока:
    begin_nested() сам делает flush всего, что ожидало до входа, и эта ошибка
    вылетела бы вне SAVEPOINT.

        with unique_guard(db, "DUPLICATE", "Уже существует"):
            db.add(obj)
    """
    try:
        with db.begin_nested():
            yield
            db.flush()
    except IntegrityError as exc:
        raise BusinessConflict(message, code=code) from exc
