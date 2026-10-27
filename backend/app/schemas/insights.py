from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel

from app.schemas.common import CommandModel, OutModel


class AnomalyOut(OutModel):
    id: uuid.UUID
    transaction_id: uuid.UUID | None
    category_id: uuid.UUID | None
    period_start: date | None
    period_end: date | None
    rule_code: str
    explanation: str
    actual_minor: int
    baseline_minor: int
    status: str
    created_at: datetime
    my_feedback: str | None = None


class AnomalyFeedbackIn(CommandModel):
    label: Literal["expected", "useful", "wrong"]


class RecommendationOut(OutModel):
    id: uuid.UUID
    category_id: uuid.UUID | None
    goal_id: uuid.UUID | None
    rule_code: str
    facts: dict[str, Any]
    text: str
    priority: int
    status: str
    expires_at: datetime | None
    created_at: datetime


class RecommendationFeedbackIn(CommandModel):
    action: Literal["useful", "hidden"]


class ForecastCategoryOut(OutModel):
    category_id: uuid.UUID
    predicted_minor: int
    lower_minor: int | None
    upper_minor: int | None


class ForecastView(BaseModel):


    availability: Literal["ready", "insufficient_history", "pending", "stale", "unavailable"]
    target_month: date
    predicted_minor: int | None = None
    lower_minor: int | None = None
    upper_minor: int | None = None
    interval_level: float | None = None
    history_start: date | None = None
    history_end: date | None = None
    model_version: str | None = None
    generated_at: datetime | None = None
    categories: list[ForecastCategoryOut] = []


class NotificationOut(OutModel):
    id: uuid.UUID
    type: str
    payload: dict[str, Any] | None
    created_at: datetime
    read_at: datetime | None


class ConsentSetIn(CommandModel):
    enabled: bool
    text_version: str


class ConsentOut(BaseModel):
    purpose: str
    enabled: bool
    text_version: str | None
    granted_at: datetime | None
    revoked_at: datetime | None


class HistoryMonthSetIn(CommandModel):
    completeness: Literal["complete", "partial", "unknown"]


class HistoryMonthOut(OutModel):
    month: date
    completeness: str
    confirmed_by: uuid.UUID | None
    confirmed_at: datetime | None
    version: int


class SummarySnapshot(BaseModel):
    period_start: date
    period_end: date
    income_minor: int
    gross_expense_minor: int
    refund_minor: int
    net_expense_minor: int
    cashflow_minor: int
    budget_remaining_minor: int | None
    source_data_version: int
    generated_at: datetime
    freshness: Literal["fresh"] = "fresh"


class CategoryMetric(BaseModel):
    category_id: uuid.UUID | None
    category_name: str | None
    gross_expense_minor: int
    refund_minor: int
    net_expense_minor: int
    share_percent: float | None   # None при нулевых валовых расходах (BR-08)
