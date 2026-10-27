"""Финансовые операции (FR-11, FR-12, FR-18, FR-19; BR-01, BR-06; DR-05…DR-07).

Каждая команда следует транзакционной границе из архитектуры, п. 5.4:
  1) блокировка строки семьи и повторная проверка прав,
  2) проверка версии/правил, 3) изменение, 4) change_log + audit + outbox.
commit выполняет вызывающий код.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, or_, select, tuple_
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.cursor import decode_cursor, encode_cursor, filters_hash
from app.core.errors import (
    AccessDenied,
    BusinessConflict,
    NotFound,
    ValidationFailed,
    field_error,
)
from app.core.utils import escape_like, today_in, utcnow
from app.crud._common import (
    authorize,
    ensure_version,
    record_change,
    require_version,
    unique_guard,
)
from app.crud.category import auto_categorize, fallback_category, get_accessible_category
from app.models import ConsumedEntityId, Household, Transaction
from app.models.enums import CategorizationMethod, MemberRole, TransactionType
from app.schemas.transaction import (
    TransactionCreate,
    TransactionFilter,
    TransactionListSummary,
    TransactionOut,
    TransactionPatch,
)

ENTITY = "transaction"
EVENT = "TransactionChanged"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


def _payload(tx: Transaction) -> dict[str, Any]:
    return TransactionOut.model_validate(tx).model_dump(mode="json")


def _tombstone(tx: Transaction) -> dict[str, Any]:
    return {"id": str(tx.id), "deleted_at": tx.deleted_at.isoformat() if tx.deleted_at else None, "version": int(tx.version)}


def _int(value: Any) -> int:
    return int(value or 0)


# --------------------------------------------------------------------------- #
# Проверки
# --------------------------------------------------------------------------- #
def _check_not_future(operation_date: date, household: Household) -> None:
    """DR-06: фактическая дата не позже текущей даты семьи."""
    if operation_date > today_in(household.timezone):
        raise ValidationFailed(
            "Дата операции не может быть в будущем",
            field_errors=[field_error("operation_date", "Дата операции не может быть в будущем")],
        )


def _lock_original(db: Session, household_id: uuid.UUID, original_id: uuid.UUID) -> Transaction:
    """Блокировка исходной покупки FOR UPDATE: конкурентные возвраты не превысят сумму (п. 6.3)."""
    original = db.execute(
        select(Transaction)
        .where(
            Transaction.id == original_id,
            Transaction.household_id == household_id,
            Transaction.deleted_at.is_(None),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if original is None:
        raise ValidationFailed(
            "Исходная покупка не найдена",
            field_errors=[field_error("original_transaction_id", "Исходная покупка не найдена")],
        )
    return original


def _refunded_total(db: Session, original_id: uuid.UUID, *, exclude_id: uuid.UUID | None = None) -> int:
    stmt = select(func.coalesce(func.sum(Transaction.amount_minor), 0)).where(
        Transaction.original_transaction_id == original_id,
        Transaction.type == TransactionType.REFUND.value,
        Transaction.deleted_at.is_(None),
    )
    if exclude_id is not None:
        stmt = stmt.where(Transaction.id != exclude_id)
    return _int(db.execute(stmt).scalar_one())


def _active_refunds(db: Session, original_id: uuid.UUID) -> list[Transaction]:
    return list(
        db.execute(
            select(Transaction)
            .where(
                Transaction.original_transaction_id == original_id,
                Transaction.type == TransactionType.REFUND.value,
                Transaction.deleted_at.is_(None),
            )
            .with_for_update()
        ).scalars().all()
    )


def _check_refund_amount(db: Session, original: Transaction, amount: int, *, exclude_id: uuid.UUID | None = None) -> None:
    """BR-06: сумма активных возвратов покупки не превышает её сумму."""
    already = _refunded_total(db, original.id, exclude_id=exclude_id)
    if already + amount > _int(original.amount_minor):
        raise BusinessConflict(
            "Сумма возвратов превышает сумму покупки",
            code="REFUND_EXCEEDS_PURCHASE",
            extra={"refundable_minor": max(_int(original.amount_minor) - already, 0)},
        )


def _is_consumed(db: Session, household_id: uuid.UUID, entity_id: uuid.UUID) -> bool:
    return db.get(ConsumedEntityId, (household_id, ENTITY, entity_id)) is not None


def _can_edit(tx: Transaction, user_id: uuid.UUID, role: str) -> bool:
    """Автор редактирует свои записи, владелец — любые (п. 3.4)."""
    return role == MemberRole.OWNER.value or tx.author_user_id == user_id


# --------------------------------------------------------------------------- #
# Create
# --------------------------------------------------------------------------- #
def create_transaction(
    db: Session,
    ctx: RequestContext,
    data: TransactionCreate,
    *,
    source: str = "manual",
    external_id: str | None = None,
    import_batch_id: uuid.UUID | None = None,
    correlation_id: uuid.UUID | None = None,
) -> tuple[Transaction, bool]:
    """POST /households/{h}/transactions. Возвращает (операция, created).

    created=False — запись с этим UUID уже создана этим же пользователем (безопасный повтор
    при потере ответа). Автор, семья, source и версия назначаются сервером.
    """
    household, member = authorize(db, ctx, lock=True)

    existing = db.get(Transaction, data.id)
    if existing is not None:
        if existing.household_id == household.id and existing.author_user_id == ctx.user_id and existing.deleted_at is None:
            return existing, False
        # чужая или удалённая запись: ничего не раскрываем и не «воскрешаем»
        raise BusinessConflict("Идентификатор операции уже использован", code="ENTITY_ID_CONFLICT")
    if _is_consumed(db, household.id, data.id):
        raise BusinessConflict("Идентификатор операции уже использован", code="ENTITY_ID_CONFLICT")

    _check_not_future(data.operation_date, household)

    category_id: uuid.UUID | None = None
    method = CategorizationMethod.NONE.value
    original_id: uuid.UUID | None = None
    tx_type = data.type

    if tx_type in (TransactionType.INCOME.value, TransactionType.EXPENSE.value):
        if data.original_transaction_id is not None:
            raise ValidationFailed(field_errors=[field_error("original_transaction_id", "Только для возврата")])
        if data.category_id is not None:
            category = get_accessible_category(db, household.id, data.category_id)
            if category.type != tx_type:
                raise ValidationFailed(field_errors=[field_error("category_id", "Тип категории не соответствует типу операции")])
            if category.is_archived:
                raise ValidationFailed(field_errors=[field_error("category_id", "Категория архивирована")])
            category_id, method = category.id, CategorizationMethod.MANUAL.value
        else:
            category_id, method = auto_categorize(db, household.id, tx_type, data.merchant, data.description)
            if category_id is None:
                category_id = fallback_category(db, tx_type).id  # «Без категории»; method остаётся none

    elif tx_type == TransactionType.REFUND.value:
        if data.original_transaction_id is None:
            raise ValidationFailed(field_errors=[field_error("original_transaction_id", "Укажите исходную покупку")])
        original = _lock_original(db, household.id, data.original_transaction_id)
        if original.type != TransactionType.EXPENSE.value:
            raise ValidationFailed(field_errors=[field_error("original_transaction_id", "Возврат возможен только для расхода")])
        if original.currency != data.currency:
            raise ValidationFailed(field_errors=[field_error("currency", "Валюта возврата должна совпадать с покупкой")])
        _check_refund_amount(db, original, data.amount_minor)
        original_id = original.id
        category_id = original.category_id  # возврат наследует категорию покупки (BR-01)
        method = original.categorization_method

    else:  # transfer: не участвует в доходах и расходах
        if data.original_transaction_id is not None:
            raise ValidationFailed(field_errors=[field_error("original_transaction_id", "Только для возврата")])
        category_id = None

    tx = Transaction(
        id=data.id,
        household_id=household.id,
        author_user_id=ctx.user_id,
        type=tx_type,
        amount_minor=data.amount_minor,
        currency=data.currency,
        operation_date=data.operation_date,
        category_id=category_id,
        merchant=data.merchant,
        description=data.description,
        source=source,
        external_id=external_id,
        original_transaction_id=original_id,
        import_batch_id=import_batch_id,
        categorization_method=method,
        version=1,
    )
    with unique_guard(db, "DUPLICATE_EXTERNAL_ID", "Операция с таким external_id уже импортирована"):
        db.add(tx)
    db.refresh(tx)  # подтягиваем связь author (selectin) и серверные значения

    record_change(
        db, household, actor_id=ctx.user_id, entity_type=ENTITY, entity_id=tx.id, action="create",
        entity_version=1, payload=_payload(tx), event_type=EVENT, correlation_id=correlation_id,
    )
    return tx, True


# --------------------------------------------------------------------------- #
# Read
# --------------------------------------------------------------------------- #
def get_transaction(db: Session, ctx: RequestContext, tx_id: uuid.UUID, *, include_deleted: bool = False) -> Transaction:
    """GET /transactions/{id}. Чужая семья и несуществующая запись -> одинаковый 404."""
    household, _ = authorize(db, ctx)
    stmt = select(Transaction).where(Transaction.id == tx_id, Transaction.household_id == household.id)
    if not include_deleted:
        stmt = stmt.where(Transaction.deleted_at.is_(None))
    tx = db.execute(stmt).scalar_one_or_none()
    if tx is None:
        raise NotFound("Операция не найдена")
    return tx


def _filter_conditions(household_id: uuid.UUID, f: TransactionFilter) -> list[Any]:
    conds: list[Any] = [Transaction.household_id == household_id, Transaction.deleted_at.is_(None)]
    if f.date_from is not None:
        conds.append(Transaction.operation_date >= f.date_from)
    if f.date_to is not None:
        conds.append(Transaction.operation_date <= f.date_to)
    if f.type is not None:
        conds.append(Transaction.type == f.type)
    if f.category_id is not None:
        conds.append(Transaction.category_id == f.category_id)
    if f.author_id is not None:
        conds.append(Transaction.author_user_id == f.author_id)
    if f.q:
        pattern = f"%{escape_like(f.q.strip())}%"
        conds.append(
            or_(Transaction.merchant.ilike(pattern, escape="\\"), Transaction.description.ilike(pattern, escape="\\"))
        )
    return conds


def summarize(db: Session, conds: list[Any]) -> TransactionListSummary:
    """Итоги по ВСЕЙ выборке (FR-19); переводы исключаются из I, E и R (BR-05)."""
    rows = db.execute(
        select(Transaction.type, func.count(), func.coalesce(func.sum(Transaction.amount_minor), 0))
        .where(*conds)
        .group_by(Transaction.type)
    ).all()
    count = 0
    totals = {t.value: 0 for t in TransactionType}
    for type_, cnt, total in rows:
        count += int(cnt)
        totals[type_] = _int(total)
    income, gross, refund = totals["income"], totals["expense"], totals["refund"]
    net = gross - refund
    return TransactionListSummary(
        count=count, income_minor=income, gross_expense_minor=gross, refund_minor=refund,
        net_expense_minor=net, cashflow_minor=income - net,
    )


def list_transactions(
    db: Session,
    ctx: RequestContext,
    flt: TransactionFilter | None = None,
    *,
    cursor: str | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[list[Transaction], str | None, bool, TransactionListSummary]:
    """GET /transactions. Сортировка: дата DESC, id DESC; keyset-пагинация без OFFSET.

    Возвращает (items, next_cursor, has_more, summary)."""
    household, _ = authorize(db, ctx)
    flt = flt or TransactionFilter()
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    if flt.date_from and flt.date_to and flt.date_from > flt.date_to:
        raise ValidationFailed(field_errors=[field_error("from", "Начало периода позже конца")])

    conds = _filter_conditions(household.id, flt)
    fhash = filters_hash(flt.model_dump(mode="json"))

    page_conds = list(conds)
    if cursor:
        data = decode_cursor(cursor)
        if data.get("f") != fhash:
            raise ValidationFailed("Курсор не соответствует фильтрам", code="INVALID_CURSOR")
        try:
            last_date, last_id = date.fromisoformat(data["d"]), uuid.UUID(data["i"])
        except (KeyError, ValueError):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        page_conds.append(tuple_(Transaction.operation_date, Transaction.id) < tuple_(last_date, last_id))

    rows = list(
        db.execute(
            select(Transaction)
            .where(*page_conds)
            .order_by(Transaction.operation_date.desc(), Transaction.id.desc())
            .limit(limit + 1)
        ).scalars().all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor({"d": last.operation_date.isoformat(), "i": str(last.id), "f": fhash})
    return items, next_cursor, has_more, summarize(db, conds)


# --------------------------------------------------------------------------- #
# Update
# --------------------------------------------------------------------------- #
def update_transaction(
    db: Session,
    ctx: RequestContext,
    tx_id: uuid.UUID,
    patch: TransactionPatch,
    expected_version: int | None,
    *,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    """PATCH /transactions/{id} (If-Match). Тип менять нельзя.

    * автор правит свои операции, владелец — любые (с пометкой в аудите);
    * смена категории расхода переносится на его возвраты в той же транзакции;
    * уменьшение суммы покупки с активными возвратами блокируется (BR-06);
    * сумма возврата проверяется под блокировкой исходной покупки.
    """
    expected = require_version(expected_version)
    household, member = authorize(db, ctx, lock=True)

    tx = db.execute(
        select(Transaction)
        .where(Transaction.id == tx_id, Transaction.household_id == household.id, Transaction.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if tx is None:
        raise NotFound("Операция не найдена")
    if not _can_edit(tx, ctx.user_id, member.role):
        raise AccessDenied("Изменять чужие операции может только владелец семьи")
    ensure_version(_int(tx.version), expected, _payload(tx))

    data = patch.model_dump(exclude_unset=True)
    refunds_to_update: list[Transaction] = []

    if data.get("amount_minor") is not None and data["amount_minor"] != _int(tx.amount_minor):
        new_amount = int(data["amount_minor"])
        if tx.type == TransactionType.REFUND.value:
            original = _lock_original(db, household.id, tx.original_transaction_id)
            _check_refund_amount(db, original, new_amount, exclude_id=tx.id)
        elif tx.type == TransactionType.EXPENSE.value and new_amount < _int(tx.amount_minor):
            if _refunded_total(db, tx.id) > 0:
                raise BusinessConflict(
                    "У покупки есть возвраты: сначала исправьте их", code="PURCHASE_HAS_REFUNDS"
                )
        tx.amount_minor = new_amount

    if data.get("operation_date") is not None:
        _check_not_future(data["operation_date"], household)
        tx.operation_date = data["operation_date"]

    if "merchant" in data:
        tx.merchant = data["merchant"]
    if "description" in data:
        tx.description = data["description"]

    if "category_id" in data:
        if tx.type in (TransactionType.REFUND.value, TransactionType.TRANSFER.value):
            if data["category_id"] is not None and data["category_id"] != tx.category_id:
                raise ValidationFailed(
                    field_errors=[field_error("category_id", "У возврата и перевода категория не меняется отдельно")]
                )
        elif data["category_id"] is None:
            raise ValidationFailed(field_errors=[field_error("category_id", "Категория обязательна")])
        elif data["category_id"] != tx.category_id:
            category = get_accessible_category(db, household.id, data["category_id"])
            if category.type != tx.type:
                raise ValidationFailed(field_errors=[field_error("category_id", "Тип категории не соответствует типу операции")])
            if category.is_archived:
                raise ValidationFailed(field_errors=[field_error("category_id", "Категория архивирована")])
            tx.category_id = category.id
            # ручной выбор не перезаписывается последующим расчётом (BR-01)
            tx.categorization_method = CategorizationMethod.MANUAL.value
            tx.category_confidence = None
            tx.category_model_version = None
            if tx.type == TransactionType.EXPENSE.value:
                refunds_to_update = _active_refunds(db, tx.id)

    tx.version = _int(tx.version) + 1
    db.flush()
    db.refresh(tx)

    by_owner = tx.author_user_id != ctx.user_id
    record_change(
        db, household, actor_id=ctx.user_id, entity_type=ENTITY, entity_id=tx.id, action="update",
        entity_version=_int(tx.version), payload=_payload(tx), event_type=EVENT, correlation_id=correlation_id,
        audit_action="transaction.update_by_owner" if by_owner else "transaction.update",
        audit_details={"author_user_id": str(tx.author_user_id) if tx.author_user_id else None} if by_owner else None,
    )

    for refund in refunds_to_update:  # отдельные change_log для изменённых возвратов (п. 7.4)
        refund.category_id = tx.category_id
        refund.categorization_method = tx.categorization_method
        refund.category_confidence = None
        refund.category_model_version = None
        refund.version = _int(refund.version) + 1
        db.flush()
        db.refresh(refund)
        record_change(
            db, household, actor_id=ctx.user_id, entity_type=ENTITY, entity_id=refund.id, action="update",
            entity_version=_int(refund.version), payload=_payload(refund), event_type=EVENT,
            correlation_id=correlation_id, audit_action="transaction.category_propagated",
        )
    return tx


# --------------------------------------------------------------------------- #
# Delete
# --------------------------------------------------------------------------- #
def delete_transaction(
    db: Session,
    ctx: RequestContext,
    tx_id: uuid.UUID,
    expected_version: int | None,
    *,
    correlation_id: uuid.UUID | None = None,
) -> Transaction:
    """DELETE /transactions/{id} (If-Match): мягкое удаление с tombstone для синхронизации.

    Покупку с активными возвратами удалить нельзя (BR-06). UUID заносится в реестр
    использованных, чтобы старый create не воскресил запись."""
    expected = require_version(expected_version)
    household, member = authorize(db, ctx, lock=True)

    tx = db.execute(
        select(Transaction)
        .where(Transaction.id == tx_id, Transaction.household_id == household.id, Transaction.deleted_at.is_(None))
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if tx is None:
        raise NotFound("Операция не найдена")
    if not _can_edit(tx, ctx.user_id, member.role):
        raise AccessDenied("Удалять чужие операции может только владелец семьи")
    ensure_version(_int(tx.version), expected, _payload(tx))

    if tx.type == TransactionType.EXPENSE.value and _refunded_total(db, tx.id) > 0:
        raise BusinessConflict("У покупки есть возвраты: сначала удалите их", code="PURCHASE_HAS_REFUNDS")

    tx.deleted_at = utcnow()
    tx.version = _int(tx.version) + 1
    if db.get(ConsumedEntityId, (household.id, ENTITY, tx.id)) is None:
        db.add(ConsumedEntityId(household_id=household.id, entity_type=ENTITY, entity_id=tx.id, deleted_at=tx.deleted_at))
    db.flush()

    by_owner = tx.author_user_id != ctx.user_id
    record_change(
        db, household, actor_id=ctx.user_id, entity_type=ENTITY, entity_id=tx.id, action="delete",
        entity_version=_int(tx.version), payload=_tombstone(tx), event_type=EVENT, correlation_id=correlation_id,
        audit_action="transaction.delete_by_owner" if by_owner else "transaction.delete",
    )
    return tx
