from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import AmountMinor, CommandModel, Currency, OutModel, Page, Trimmed


class TransactionCreate(CommandModel):
    id: uuid.UUID  # создаётся клиентом (в том числе без сети)
    type: Literal["income", "expense", "refund", "transfer"]
    amount_minor: AmountMinor
    currency: Currency = "BYN"
    operation_date: date
    category_id: uuid.UUID | None = None
    merchant: Trimmed | None = Field(default=None, max_length=120)
    description: Trimmed | None = Field(default=None, max_length=500)
    original_transaction_id: uuid.UUID | None = None


class TransactionPatch(CommandModel):
    """Тип менять нельзя. Поля, не переданные клиентом, не изменяются
    (используется model_fields_set), переданный null очищает необязательное поле."""

    amount_minor: AmountMinor | None = None
    operation_date: date | None = None
    category_id: uuid.UUID | None = None
    merchant: Trimmed | None = Field(default=None, max_length=120)
    description: Trimmed | None = Field(default=None, max_length=500)


class TransactionOut(OutModel):
    id: uuid.UUID
    type: str
    amount_minor: int
    currency: str
    operation_date: date
    category_id: uuid.UUID | None
    merchant: str | None
    description: str | None
    original_transaction_id: uuid.UUID | None
    author_user_id: uuid.UUID | None
    author_display_name: str
    source: str
    categorization_method: str
    category_confidence: Decimal | None
    version: int
    created_at: datetime
    updated_at: datetime


class TransactionFilter(BaseModel):
    date_from: date | None = None
    date_to: date | None = None
    type: Literal["income", "expense", "refund", "transfer"] | None = None
    category_id: uuid.UUID | None = None
    author_id: uuid.UUID | None = None
    q: str | None = Field(default=None, max_length=120)


class TransactionListSummary(BaseModel):
    """Итоги по всей выборке, а не по странице (FR-19)."""

    count: int
    income_minor: int
    gross_expense_minor: int
    refund_minor: int
    net_expense_minor: int
    cashflow_minor: int


class TransactionPage(Page[TransactionOut]):
    summary: TransactionListSummary
