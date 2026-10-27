from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import Field, field_validator

from app.schemas.common import AmountMinor, CommandModel, OutModel, Trimmed


class GoalCreate(CommandModel):
    title: Trimmed = Field(min_length=1, max_length=120)
    target_minor: AmountMinor
    target_date: date


class GoalPatch(CommandModel):
    title: Trimmed | None = Field(default=None, min_length=1, max_length=120)
    target_minor: AmountMinor | None = None
    target_date: date | None = None
    status: Literal["active", "archived"] | None = None


class GoalOut(OutModel):
    id: uuid.UUID
    title: str
    target_minor: int
    target_date: date
    status: str
    version: int
    accumulated_minor: int
    progress_percent: float
    suggested_monthly_minor: int | None
    created_at: datetime
    updated_at: datetime


def _nonzero(value: int | None) -> int | None:
    if value == 0:
        raise ValueError("Сумма движения не может быть равна нулю")
    return value


class ContributionCreate(CommandModel):
    id: uuid.UUID
    signed_amount_minor: int = Field(ge=-999_999_999_999, le=999_999_999_999)
    occurred_on: date
    note: Trimmed | None = Field(default=None, max_length=255)

    _check_amount = field_validator("signed_amount_minor")(_nonzero)


class ContributionPatch(CommandModel):
    signed_amount_minor: int | None = Field(default=None, ge=-999_999_999_999, le=999_999_999_999)
    note: Trimmed | None = Field(default=None, max_length=255)

    _check_amount = field_validator("signed_amount_minor")(_nonzero)


class ContributionOut(OutModel):
    id: uuid.UUID
    goal_id: uuid.UUID
    author_user_id: uuid.UUID | None
    signed_amount_minor: int
    occurred_on: date
    note: str | None
    version: int
