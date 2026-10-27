from __future__ import annotations

import uuid
from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import CommandModel, MAX_AMOUNT_MINOR, OutModel


class CategoryLimitIn(CommandModel):
    category_id: uuid.UUID
    limit_minor: int = Field(ge=1, le=MAX_AMOUNT_MINOR)


class BudgetUpsert(CommandModel):
    total_limit_minor: int | None = Field(default=None, ge=1, le=MAX_AMOUNT_MINOR)
    planned_income_minor: int | None = Field(default=None, ge=0, le=MAX_AMOUNT_MINOR)
    category_limits: list[CategoryLimitIn] = Field(default_factory=list, max_length=200)


class CategoryLimitOut(OutModel):
    category_id: uuid.UUID
    limit_minor: int


class BudgetOut(BaseModel):
    id: uuid.UUID
    household_id: uuid.UUID
    month: date
    currency: str
    version: int
    total_limit_minor: int | None
    planned_income_minor: int | None
    category_limits: list[CategoryLimitOut]
    # Фактические показатели вычисляются из операций (SRD 11.7)
    net_expense_minor: int
    remaining_minor: int | None        # отрицательный остаток = превышение
    usage_percent: float | None        # None, если лимит не задан («Лимит не задан»)
    limit_set: bool
