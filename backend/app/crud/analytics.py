"""Детерминированные агрегаты (архитектура 11.2, BR-05…BR-09).

Все суммы считаются по исходным значениям в копейках; округляются только проценты.
Эти функции не зависят от ML-моделей и worker-ов."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import ValidationFailed, field_error
from app.core.utils import first_day_of_month, last_day_of_month, utcnow
from app.crud._common import authorize
from app.models import Budget, Category, Transaction
from app.models.enums import TransactionType
from app.schemas.insights import CategoryMetric, SummarySnapshot


def _int(value: Any) -> int:
    return int(value or 0)


def period_totals(db: Session, household_id: uuid.UUID, start: date, end: date) -> dict[str, int]:
    """BR-05: I = сумма income; E = expense; R = refund; X = E − R; C = I − X.
    Переводы исключены. Период включает обе даты. Возврат относится к дате возврата (BR-06)."""
    rows = db.execute(
        select(Transaction.type, func.coalesce(func.sum(Transaction.amount_minor), 0))
        .where(
            Transaction.household_id == household_id,
            Transaction.deleted_at.is_(None),
            Transaction.operation_date >= start,
            Transaction.operation_date <= end,
        )
        .group_by(Transaction.type)
    ).all()
    by_type = {t: _int(v) for t, v in rows}
    income = by_type.get(TransactionType.INCOME.value, 0)
    gross = by_type.get(TransactionType.EXPENSE.value, 0)
    refund = by_type.get(TransactionType.REFUND.value, 0)
    net = gross - refund
    return {
        "income_minor": income,
        "gross_expense_minor": gross,
        "refund_minor": refund,
        "net_expense_minor": net,
        "cashflow_minor": income - net,
    }


def category_totals(db: Session, household_id: uuid.UUID, start: date, end: date) -> list[CategoryMetric]:
    """Расходы по категориям (FR-22). Доля = валовые расходы категории / общие валовые × 100 (BR-08);
    при нулевых валовых расходах доли не вычисляются. Отрицательные чистые значения не скрываются."""
    rows = db.execute(
        select(Transaction.category_id, Transaction.type, func.coalesce(func.sum(Transaction.amount_minor), 0))
        .where(
            Transaction.household_id == household_id,
            Transaction.deleted_at.is_(None),
            Transaction.type.in_([TransactionType.EXPENSE.value, TransactionType.REFUND.value]),
            Transaction.operation_date >= start,
            Transaction.operation_date <= end,
        )
        .group_by(Transaction.category_id, Transaction.type)
    ).all()

    gross: dict[uuid.UUID | None, int] = {}
    refund: dict[uuid.UUID | None, int] = {}
    for category_id, type_, total in rows:
        target = gross if type_ == TransactionType.EXPENSE.value else refund
        target[category_id] = target.get(category_id, 0) + _int(total)

    ids = set(gross) | set(refund)
    names: dict[uuid.UUID, str] = {}
    real_ids = [i for i in ids if i is not None]
    if real_ids:
        names = dict(db.execute(select(Category.id, Category.name).where(Category.id.in_(real_ids))).all())

    total_gross = sum(gross.values())
    metrics: list[CategoryMetric] = []
    for cid in ids:
        g, r = gross.get(cid, 0), refund.get(cid, 0)
        metrics.append(
            CategoryMetric(
                category_id=cid,
                category_name=names.get(cid) if cid is not None else None,
                gross_expense_minor=g,
                refund_minor=r,
                net_expense_minor=g - r,
                share_percent=round(g / total_gross * 100, 1) if total_gross > 0 else None,
            )
        )
    metrics.sort(key=lambda m: m.gross_expense_minor, reverse=True)
    return metrics


def get_summary(db: Session, ctx: RequestContext, start: date, end: date) -> SummarySnapshot:
    """GET /analytics/summary. budget_remaining_minor заполняется, если период внутри одного
    месяца и для месяца задан общий лимит (остаток = лимит − чистые расходы месяца, BR-08)."""
    household, _ = authorize(db, ctx)
    if start > end:
        raise ValidationFailed(field_errors=[field_error("from", "Начало периода позже конца")])
    totals = period_totals(db, household.id, start, end)

    remaining: int | None = None
    if first_day_of_month(start) == first_day_of_month(end):
        month = first_day_of_month(start)
        budget = db.execute(
            select(Budget).where(Budget.household_id == household.id, Budget.month == month)
        ).scalar_one_or_none()
        if budget is not None and budget.total_limit_minor is not None:
            month_totals = period_totals(db, household.id, month, last_day_of_month(month))
            remaining = int(budget.total_limit_minor) - month_totals["net_expense_minor"]

    return SummarySnapshot(
        period_start=start,
        period_end=end,
        budget_remaining_minor=remaining,
        source_data_version=int(household.data_version),
        generated_at=utcnow(),
        **totals,
    )


def get_category_metrics(db: Session, ctx: RequestContext, start: date, end: date) -> list[CategoryMetric]:
    """GET /analytics/categories (без сравнения с прошлым периодом — оно считается в analytics worker)."""
    household, _ = authorize(db, ctx)
    if start > end:
        raise ValidationFailed(field_errors=[field_error("from", "Начало периода позже конца")])
    return category_totals(db, household.id, start, end)
