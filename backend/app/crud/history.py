"""Признак полноты истории по месяцам (DR-04): подтверждает владелец."""
from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import PreconditionRequired, ValidationFailed, field_error
from app.core.utils import parse_month, today_in, utcnow
from app.crud._common import add_audit, authorize, ensure_version
from app.models import HistoryMonth


def set_history_month(
    db: Session, ctx: RequestContext, month: str | date, completeness: str, expected_version: int | None = None
) -> HistoryMonth:
    """PUT /history-months/{month}. Для существующей записи нужен If-Match."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    month_d = parse_month(month)
    if month_d >= today_in(household.timezone).replace(day=1):
        raise ValidationFailed(field_errors=[field_error("month", "Подтверждать можно только завершённые месяцы")])
    row = db.execute(
        select(HistoryMonth).where(HistoryMonth.household_id == household.id, HistoryMonth.month == month_d)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if row is None:
        row = HistoryMonth(household_id=household.id, month=month_d, completeness=completeness, version=1,
                           confirmed_by=ctx.user_id, confirmed_at=utcnow())
        db.add(row)
    else:
        if expected_version is None:
            raise PreconditionRequired("Необходимо передать версию записи (If-Match)")
        ensure_version(int(row.version), expected_version)
        row.completeness = completeness
        row.confirmed_by = ctx.user_id
        row.confirmed_at = utcnow()
        row.version = int(row.version) + 1
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="history_month.set",
              target_type="history_month", target_id=f"{household.id}:{month_d}")
    db.flush()
    return row


def count_complete_months(db: Session, household_id) -> int:
    return len(db.execute(
        select(HistoryMonth.month).where(HistoryMonth.household_id == household_id, HistoryMonth.completeness == "complete")
    ).all())
