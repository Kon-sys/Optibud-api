"""Бюджеты и лимиты (FR-07, FR-08; SRD 11.7)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import BusinessConflict, NotFound, PreconditionRequired, ValidationFailed, field_error
from app.core.utils import first_day_of_month, last_day_of_month, parse_month
from app.crud._common import authorize, ensure_version, record_change, unique_guard
from app.crud.analytics import period_totals
from app.crud.category import get_accessible_category
from app.models import Budget, BudgetCategoryLimit
from app.models.enums import CategoryType
from app.schemas.budget import BudgetOut, BudgetUpsert, CategoryLimitOut

ENTITY = "budget"
EVENT = "BudgetChanged"


def budget_view(db: Session, budget: Budget) -> BudgetOut:
    """Фактические показатели вычисляются из операций, а не хранятся (SRD 11.7)."""
    month = budget.month
    totals = period_totals(db, budget.household_id, month, last_day_of_month(month))
    net = totals["net_expense_minor"]
    limit = int(budget.total_limit_minor) if budget.total_limit_minor is not None else None
    return BudgetOut(
        id=budget.id,
        household_id=budget.household_id,
        month=month,
        currency=budget.currency,
        version=int(budget.version),
        total_limit_minor=limit,
        planned_income_minor=int(budget.planned_income_minor) if budget.planned_income_minor is not None else None,
        category_limits=[CategoryLimitOut(category_id=l.category_id, limit_minor=int(l.limit_minor)) for l in budget.limits],
        net_expense_minor=net,
        remaining_minor=(limit - net) if limit is not None else None,     # < 0 — превышение
        usage_percent=round(net / limit * 100, 1) if limit else None,      # None: «Лимит не задан»
        limit_set=limit is not None,
    )


def get_budget(db: Session, ctx: RequestContext, month: str | date) -> Budget:
    """GET /budgets/{month}; 404, если бюджета на месяц нет."""
    household, _ = authorize(db, ctx)
    month_d = parse_month(month)
    budget = db.execute(
        select(Budget).where(Budget.household_id == household.id, Budget.month == month_d)
    ).scalar_one_or_none()
    if budget is None:
        raise NotFound("Бюджет на этот месяц не задан")
    return budget


def upsert_budget(
    db: Session,
    ctx: RequestContext,
    month: str | date,
    data: BudgetUpsert,
    *,
    expected_version: int | None = None,
    create_only: bool = False,
) -> Budget:
    """PUT /budgets/{month} (только владелец).

    Существующий период требует If-Match (expected_version); создание — If-None-Match: * (create_only=True).
    Общий лимит и лимиты категорий меняются одной проверяемой операцией; сумма лимитов категорий
    не превышает общий, если он задан. Изменение лимита исторические операции не меняет (FR-07)."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    month_d = parse_month(month)

    # Проверки входных данных
    if len({l.category_id for l in data.category_limits}) != len(data.category_limits):
        raise ValidationFailed(field_errors=[field_error("category_limits", "Категории не должны повторяться")])
    limits_sum = sum(l.limit_minor for l in data.category_limits)
    if data.total_limit_minor is not None and limits_sum > data.total_limit_minor:
        raise ValidationFailed(
            "Сумма лимитов категорий превышает общий лимит",
            field_errors=[field_error("category_limits", "Сумма лимитов категорий превышает общий лимит")],
        )
    for item in data.category_limits:
        category = get_accessible_category(db, household.id, item.category_id, field="category_limits")
        if category.type != CategoryType.EXPENSE.value:
            raise ValidationFailed(field_errors=[field_error("category_limits", "Лимиты задаются для категорий расходов")])

    budget = db.execute(
        select(Budget).where(Budget.household_id == household.id, Budget.month == month_d)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()

    if budget is None:
        if expected_version is not None and not create_only:
            raise NotFound("Бюджет на этот месяц не задан")
        budget = Budget(
            id=uuid.uuid4(), household_id=household.id, month=month_d, currency="BYN", version=1,
            total_limit_minor=data.total_limit_minor, planned_income_minor=data.planned_income_minor,
        )
        with unique_guard(db, "BUDGET_EXISTS", "Бюджет на этот месяц уже создан"):
            db.add(budget)
        action = "create"
    else:
        if create_only:
            raise BusinessConflict("Бюджет на этот месяц уже создан", code="BUDGET_EXISTS")
        if expected_version is None:
            raise PreconditionRequired("Необходимо передать версию бюджета (If-Match)")
        ensure_version(int(budget.version), expected_version, budget_view(db, budget).model_dump(mode="json"))
        budget.total_limit_minor = data.total_limit_minor
        budget.planned_income_minor = data.planned_income_minor
        budget.version = int(budget.version) + 1
        action = "update"

    # Полная замена набора лимитов категорий
    db.flush()
    budget.limits.clear()
    db.flush()
    for item in data.category_limits:
        budget.limits.append(BudgetCategoryLimit(id=uuid.uuid4(), category_id=item.category_id, limit_minor=item.limit_minor))
    db.flush()
    db.refresh(budget)

    record_change(
        db, household, actor_id=ctx.user_id, entity_type=ENTITY, entity_id=budget.id, action=action,
        entity_version=int(budget.version), payload=budget_view(db, budget).model_dump(mode="json"), event_type=EVENT,
    )
    return budget
