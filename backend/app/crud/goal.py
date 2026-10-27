"""Финансовые цели и движения по ним (FR-32, FR-33; BR-11)."""
from __future__ import annotations

import math
import uuid
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.cursor import decode_cursor, encode_cursor, filters_hash
from app.core.errors import BusinessConflict, NotFound, ValidationFailed, field_error
from app.core.utils import months_remaining_inclusive, today_in
from app.crud._common import authorize, ensure_version, record_change, require_version, unique_guard
from app.models import ConsumedEntityId, FinancialGoal, GoalContribution
from app.models.enums import GoalStatus
from app.schemas.goal import (
    ContributionCreate,
    ContributionOut,
    ContributionPatch,
    GoalCreate,
    GoalOut,
    GoalPatch,
)

GOAL_EVENT = "GoalChanged"
DEFAULT_LIMIT = 50
MAX_LIMIT = 100


# --------------------------------------------------------------------------- #
# Расчёты (чистые функции, удобны для unit-тестов)
# --------------------------------------------------------------------------- #
def suggested_monthly(target_minor: int, accumulated_minor: int, today: date, target_date: date) -> int | None:
    """BR-11: max(цель − накопления, 0) / число оставшихся месяцев включая месяц срока.

    Округление вверх, чтобы к сроку цель была достигнута целыми копейками.
    None — срок прошёл (нет делителя, без деления на ноль)."""
    months = months_remaining_inclusive(today, target_date)
    if months <= 0:
        return None
    return math.ceil(max(target_minor - accumulated_minor, 0) / months)


def progress_percent(target_minor: int, accumulated_minor: int) -> float:
    """Процент достижения с одним знаком; ограничен диапазоном 0…100 для отображения."""
    if target_minor <= 0:
        return 0.0
    return round(min(max(accumulated_minor, 0) / target_minor * 100, 100.0), 1)


def effective_status(goal: FinancialGoal, accumulated_minor: int, today: date) -> str:
    if goal.status == GoalStatus.ARCHIVED.value:
        return GoalStatus.ARCHIVED.value
    if accumulated_minor >= int(goal.target_minor):
        return GoalStatus.ACHIEVED.value
    if goal.target_date < today:
        return GoalStatus.OVERDUE.value
    return GoalStatus.ACTIVE.value


def _accumulated(db: Session, goal_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.coalesce(func.sum(GoalContribution.signed_amount_minor), 0)).where(
                GoalContribution.goal_id == goal_id
            )
        ).scalar_one()
        or 0
    )


def goal_view(db: Session, goal: FinancialGoal, timezone: str = "Europe/Minsk") -> GoalOut:
    today = today_in(timezone)
    acc = _accumulated(db, goal.id)
    return GoalOut(
        id=goal.id,
        title=goal.title,
        target_minor=int(goal.target_minor),
        target_date=goal.target_date,
        status=effective_status(goal, acc, today),
        version=int(goal.version),
        accumulated_minor=acc,
        progress_percent=progress_percent(int(goal.target_minor), acc),
        suggested_monthly_minor=suggested_monthly(int(goal.target_minor), acc, today, goal.target_date),
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


def _sync_status(db: Session, goal: FinancialGoal, timezone: str) -> None:
    """Сохраняет вычисленный статус (achieved/overdue/active); archived не трогает."""
    status = effective_status(goal, _accumulated(db, goal.id), today_in(timezone))
    if status != goal.status:
        goal.status = status


def _goal_payload(db: Session, goal: FinancialGoal, tz: str) -> dict[str, Any]:
    return goal_view(db, goal, tz).model_dump(mode="json")


def _lock_goal(db: Session, household_id: uuid.UUID, goal_id: uuid.UUID) -> FinancialGoal:
    goal = db.execute(
        select(FinancialGoal)
        .where(FinancialGoal.id == goal_id, FinancialGoal.household_id == household_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if goal is None:
        raise NotFound("Цель не найдена")
    return goal


# --------------------------------------------------------------------------- #
# Цели
# --------------------------------------------------------------------------- #
def create_goal(db: Session, ctx: RequestContext, data: GoalCreate) -> FinancialGoal:
    """POST /goals (только владелец)."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    goal = FinancialGoal(
        id=uuid.uuid4(), household_id=household.id, title=data.title, target_minor=data.target_minor,
        target_date=data.target_date, status=GoalStatus.ACTIVE.value, version=1,
    )
    db.add(goal)
    db.flush()
    _sync_status(db, goal, household.timezone)  # срок в прошлом -> overdue
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal", entity_id=goal.id, action="create",
        entity_version=1, payload=_goal_payload(db, goal, household.timezone), event_type=GOAL_EVENT,
    )
    return goal


def get_goal(db: Session, ctx: RequestContext, goal_id: uuid.UUID) -> FinancialGoal:
    household, _ = authorize(db, ctx)
    goal = db.execute(
        select(FinancialGoal).where(FinancialGoal.id == goal_id, FinancialGoal.household_id == household.id)
    ).scalar_one_or_none()
    if goal is None:
        raise NotFound("Цель не найдена")
    return goal


def list_goals(
    db: Session, ctx: RequestContext, *, status: str | None = None, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[FinancialGoal], str | None, bool]:
    """GET /goals. Порядок: новые первыми (created_at DESC, id DESC), keyset-курсор."""
    household, _ = authorize(db, ctx)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    conds: list[Any] = [FinancialGoal.household_id == household.id]
    if status:
        conds.append(FinancialGoal.status == status)
    fhash = filters_hash({"status": status})
    if cursor:
        from datetime import datetime
        from sqlalchemy import tuple_
        data = decode_cursor(cursor)
        if data.get("f") != fhash:
            raise ValidationFailed("Курсор не соответствует фильтрам", code="INVALID_CURSOR")
        try:
            last_created, last_id = datetime.fromisoformat(data["c"]), uuid.UUID(data["i"])
        except (KeyError, ValueError):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        conds.append(tuple_(FinancialGoal.created_at, FinancialGoal.id) < tuple_(last_created, last_id))
    rows = list(
        db.execute(
            select(FinancialGoal).where(*conds)
            .order_by(FinancialGoal.created_at.desc(), FinancialGoal.id.desc()).limit(limit + 1)
        ).scalars().all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor({"c": last.created_at.isoformat(), "i": str(last.id), "f": fhash})
    return items, next_cursor, has_more


def update_goal(
    db: Session, ctx: RequestContext, goal_id: uuid.UUID, patch: GoalPatch, expected_version: int | None
) -> FinancialGoal:
    """PATCH /goals/{id} (If-Match, только владелец)."""
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    goal = _lock_goal(db, household.id, goal_id)
    ensure_version(int(goal.version), expected, _goal_payload(db, goal, household.timezone))

    data = patch.model_dump(exclude_unset=True)
    for key in ("title", "target_minor", "target_date"):
        if data.get(key) is not None:
            setattr(goal, key, data[key])
    if data.get("status") is not None:
        goal.status = data["status"]  # active | archived; achieved/overdue вычисляются
    if goal.status != GoalStatus.ARCHIVED.value:
        _sync_status(db, goal, household.timezone)
    goal.version = int(goal.version) + 1
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal", entity_id=goal.id, action="update",
        entity_version=int(goal.version), payload=_goal_payload(db, goal, household.timezone), event_type=GOAL_EVENT,
    )
    return goal


# --------------------------------------------------------------------------- #
# Движения по цели (не создают Transaction — BR-11)
# --------------------------------------------------------------------------- #
def _contribution_payload(c: GoalContribution) -> dict[str, Any]:
    return ContributionOut.model_validate(c).model_dump(mode="json")


def _touch_goal_after_change(db: Session, household, goal: FinancialGoal, ctx: RequestContext) -> None:
    """Пересчитывает статус цели и публикует её новую версию."""
    _sync_status(db, goal, household.timezone)
    goal.version = int(goal.version) + 1
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal", entity_id=goal.id, action="update",
        entity_version=int(goal.version), payload=_goal_payload(db, goal, household.timezone), event_type=GOAL_EVENT,
        audit_action="goal.progress_changed",
    )


def add_contribution(db: Session, ctx: RequestContext, goal_id: uuid.UUID, data: ContributionCreate) -> tuple[GoalContribution, bool]:
    """POST /goals/{id}/contributions. Итог цели не может стать отрицательным (проверка под блокировкой цели).
    Возвращает (движение, created); повтор с тем же id безопасен."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    goal = _lock_goal(db, household.id, goal_id)

    existing = db.get(GoalContribution, data.id)
    if existing is not None:
        if existing.household_id == household.id and existing.goal_id == goal.id and existing.author_user_id == ctx.user_id:
            return existing, False
        raise BusinessConflict("Идентификатор движения уже использован", code="ENTITY_ID_CONFLICT")
    if db.get(ConsumedEntityId, (household.id, "goal_contribution", data.id)) is not None:
        raise BusinessConflict("Идентификатор движения уже использован", code="ENTITY_ID_CONFLICT")

    if _accumulated(db, goal.id) + data.signed_amount_minor < 0:
        raise BusinessConflict("Изъятие превышает накопления по цели", code="GOAL_NEGATIVE_TOTAL")

    contribution = GoalContribution(
        id=data.id, household_id=household.id, goal_id=goal.id, author_user_id=ctx.user_id,
        signed_amount_minor=data.signed_amount_minor, occurred_on=data.occurred_on, note=data.note, version=1,
    )
    db.add(contribution)
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal_contribution", entity_id=contribution.id,
        action="create", entity_version=1, payload=_contribution_payload(contribution), event_type=GOAL_EVENT,
    )
    _touch_goal_after_change(db, household, goal, ctx)
    return contribution, True


def list_contributions(
    db: Session, ctx: RequestContext, goal_id: uuid.UUID, *, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[GoalContribution], str | None, bool]:
    """GET /goals/{id}/contributions: дата DESC, id DESC (keyset)."""
    from datetime import date as _date
    from sqlalchemy import tuple_
    household, _ = authorize(db, ctx)
    get_goal(db, ctx, goal_id)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    conds: list[Any] = [GoalContribution.goal_id == goal_id, GoalContribution.household_id == household.id]
    fhash = filters_hash({"goal": str(goal_id)})
    if cursor:
        data = decode_cursor(cursor)
        if data.get("f") != fhash:
            raise ValidationFailed("Курсор не соответствует фильтрам", code="INVALID_CURSOR")
        try:
            last_d, last_id = _date.fromisoformat(data["d"]), uuid.UUID(data["i"])
        except (KeyError, ValueError):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        conds.append(tuple_(GoalContribution.occurred_on, GoalContribution.id) < tuple_(last_d, last_id))
    rows = list(
        db.execute(
            select(GoalContribution).where(*conds)
            .order_by(GoalContribution.occurred_on.desc(), GoalContribution.id.desc()).limit(limit + 1)
        ).scalars().all()
    )
    has_more = len(rows) > limit
    items = rows[:limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        next_cursor = encode_cursor({"d": last.occurred_on.isoformat(), "i": str(last.id), "f": fhash})
    return items, next_cursor, has_more


def _lock_contribution(db: Session, household_id: uuid.UUID, goal_id: uuid.UUID, cid: uuid.UUID) -> GoalContribution:
    c = db.execute(
        select(GoalContribution)
        .where(GoalContribution.id == cid, GoalContribution.goal_id == goal_id, GoalContribution.household_id == household_id)
        .with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if c is None:
        raise NotFound("Движение не найдено")
    return c


def update_contribution(
    db: Session, ctx: RequestContext, goal_id: uuid.UUID, contribution_id: uuid.UUID,
    patch: ContributionPatch, expected_version: int | None,
) -> GoalContribution:
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    goal = _lock_goal(db, household.id, goal_id)
    c = _lock_contribution(db, household.id, goal.id, contribution_id)
    ensure_version(int(c.version), expected, _contribution_payload(c))

    data = patch.model_dump(exclude_unset=True)
    if data.get("signed_amount_minor") is not None:
        delta = data["signed_amount_minor"] - int(c.signed_amount_minor)
        if _accumulated(db, goal.id) + delta < 0:
            raise BusinessConflict("Итог цели не может быть отрицательным", code="GOAL_NEGATIVE_TOTAL")
        c.signed_amount_minor = data["signed_amount_minor"]
    if "note" in data:
        c.note = data["note"]
    c.version = int(c.version) + 1
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal_contribution", entity_id=c.id, action="update",
        entity_version=int(c.version), payload=_contribution_payload(c), event_type=GOAL_EVENT,
    )
    _touch_goal_after_change(db, household, goal, ctx)
    return c


def delete_contribution(
    db: Session, ctx: RequestContext, goal_id: uuid.UUID, contribution_id: uuid.UUID, expected_version: int | None
) -> None:
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    goal = _lock_goal(db, household.id, goal_id)
    c = _lock_contribution(db, household.id, goal.id, contribution_id)
    ensure_version(int(c.version), expected, _contribution_payload(c))
    if _accumulated(db, goal.id) - int(c.signed_amount_minor) < 0:
        raise BusinessConflict("Итог цели не может быть отрицательным", code="GOAL_NEGATIVE_TOTAL")

    version = int(c.version) + 1
    db.add(ConsumedEntityId(household_id=household.id, entity_type="goal_contribution", entity_id=c.id))
    db.delete(c)
    db.flush()
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="goal_contribution", entity_id=contribution_id,
        action="delete", entity_version=version, payload={"id": str(contribution_id), "version": version},
        event_type=GOAL_EVENT,
    )
    _touch_goal_after_change(db, household, goal, ctx)
