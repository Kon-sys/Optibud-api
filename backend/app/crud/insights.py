"""Результаты аналитики: аномалии, рекомендации, прогнозы (FR-24…FR-31, BR-10).

Создаёт их analytics worker (функции create_*), пользователь читает и ставит отметки.
Отметки хранятся отдельно и исходные данные не меняют."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import select, tuple_, update
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.cursor import decode_cursor, encode_cursor, filters_hash
from app.core.errors import NotFound, ValidationFailed
from app.core.utils import parse_month, utcnow
from app.crud._common import authorize, unique_guard
from app.crud.history import count_complete_months
from app.models import (
    Anomaly, AnomalyFeedback, Forecast, ForecastCategory, Recommendation, RecommendationFeedback,
)
from app.models.enums import ForecastStatus, ResultStatus
from app.schemas.insights import AnomalyOut, ForecastCategoryOut, ForecastView, RecommendationOut

DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MIN_HISTORY_MONTHS = 3  # FR-27


# --------------------------------------------------------------------------- #
# Аномалии
# --------------------------------------------------------------------------- #
def create_anomaly(db: Session, household_id: uuid.UUID, *, dedup_key: str, **fields: Any) -> tuple[Anomaly, bool]:
    """Для worker-а. Повторный анализ той же версии данных дубль не создаёт (dedup_key)."""
    existing = db.execute(select(Anomaly).where(Anomaly.dedup_key == dedup_key)).scalar_one_or_none()
    if existing is not None:
        return existing, False
    anomaly = Anomaly(id=uuid.uuid4(), household_id=household_id, dedup_key=dedup_key, **fields)
    db.add(anomaly)
    db.flush()
    return anomaly, True


def list_anomalies(
    db: Session, ctx: RequestContext, *, status: str | None = None, cursor: str | None = None, limit: int = DEFAULT_LIMIT
) -> tuple[list[AnomalyOut], str | None, bool]:
    household, _ = authorize(db, ctx)
    limit = max(1, min(int(limit or DEFAULT_LIMIT), MAX_LIMIT))
    conds: list[Any] = [Anomaly.household_id == household.id]
    if status:
        conds.append(Anomaly.status == status)
    fhash = filters_hash({"status": status})
    if cursor:
        data = decode_cursor(cursor)
        if data.get("f") != fhash:
            raise ValidationFailed("Курсор не соответствует фильтрам", code="INVALID_CURSOR")
        try:
            c, i = datetime.fromisoformat(data["c"]), uuid.UUID(data["i"])
        except (KeyError, ValueError):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        conds.append(tuple_(Anomaly.created_at, Anomaly.id) < tuple_(c, i))
    rows = list(db.execute(
        select(Anomaly).where(*conds).order_by(Anomaly.created_at.desc(), Anomaly.id.desc()).limit(limit + 1)
    ).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    mine = {}
    if rows:
        mine = dict(db.execute(
            select(AnomalyFeedback.anomaly_id, AnomalyFeedback.label)
            .where(AnomalyFeedback.user_id == ctx.user_id, AnomalyFeedback.anomaly_id.in_([r.id for r in rows]))
        ).all())
    items = []
    for r in rows:
        out = AnomalyOut.model_validate(r)
        out.my_feedback = mine.get(r.id)
        items.append(out)
    nxt = encode_cursor({"c": rows[-1].created_at.isoformat(), "i": str(rows[-1].id), "f": fhash}) if has_more and rows else None
    return items, nxt, has_more


def set_anomaly_feedback(db: Session, ctx: RequestContext, anomaly_id: uuid.UUID, label: str) -> AnomalyFeedback:
    """PUT /anomalies/{id}/feedback — upsert отметки пользователя (expected/useful/wrong)."""
    household, _ = authorize(db, ctx)
    anomaly = db.execute(
        select(Anomaly).where(Anomaly.id == anomaly_id, Anomaly.household_id == household.id)
    ).scalar_one_or_none()
    if anomaly is None:
        raise NotFound("Аномалия не найдена")
    fb = db.execute(
        select(AnomalyFeedback).where(AnomalyFeedback.anomaly_id == anomaly.id, AnomalyFeedback.user_id == ctx.user_id)
    ).scalar_one_or_none()
    if fb is None:
        fb = AnomalyFeedback(id=uuid.uuid4(), anomaly_id=anomaly.id, user_id=ctx.user_id, label=label)
        with unique_guard(db, "FEEDBACK_EXISTS", "Отметка уже существует"):
            db.add(fb)
    else:
        fb.label = label
        db.flush()
    return fb


# --------------------------------------------------------------------------- #
# Рекомендации
# --------------------------------------------------------------------------- #
def create_recommendation(db: Session, household_id: uuid.UUID, **fields: Any) -> Recommendation:
    rec = Recommendation(id=uuid.uuid4(), household_id=household_id, **fields)
    db.add(rec)
    db.flush()
    return rec


def list_recommendations(db: Session, ctx: RequestContext, status: str | None = ResultStatus.ACTIVE.value) -> list[Recommendation]:
    """GET /recommendations. Скрытые этим пользователем карточки не возвращаются (FR-31);
    просроченные не показываются."""
    household, _ = authorize(db, ctx)
    stmt = select(Recommendation).where(Recommendation.household_id == household.id)
    if status:
        stmt = stmt.where(Recommendation.status == status)
    hidden = select(RecommendationFeedback.recommendation_id).where(
        RecommendationFeedback.user_id == ctx.user_id, RecommendationFeedback.action == "hidden"
    )
    rows = db.execute(stmt.where(Recommendation.id.not_in(hidden)).order_by(
        Recommendation.priority.desc(), Recommendation.created_at.desc())).scalars().all()
    now = utcnow()
    from app.core.utils import as_utc
    return [r for r in rows if r.expires_at is None or as_utc(r.expires_at) > now]


def set_recommendation_feedback(db: Session, ctx: RequestContext, recommendation_id: uuid.UUID, action: str) -> RecommendationFeedback:
    """PUT /recommendations/{id}/feedback: useful | hidden. Относится только к этому пользователю."""
    household, _ = authorize(db, ctx)
    rec = db.execute(
        select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.household_id == household.id)
    ).scalar_one_or_none()
    if rec is None:
        raise NotFound("Рекомендация не найдена")
    fb = db.execute(select(RecommendationFeedback).where(
        RecommendationFeedback.recommendation_id == rec.id,
        RecommendationFeedback.user_id == ctx.user_id,
        RecommendationFeedback.action == action,
    )).scalar_one_or_none()
    if fb is None:
        fb = RecommendationFeedback(id=uuid.uuid4(), recommendation_id=rec.id, user_id=ctx.user_id, action=action)
        with unique_guard(db, "FEEDBACK_EXISTS", "Отметка уже существует"):
            db.add(fb)
    return fb


# --------------------------------------------------------------------------- #
# Прогнозы
# --------------------------------------------------------------------------- #
def create_forecast(
    db: Session, household_id: uuid.UUID, *, target_month: date, predicted_minor: int,
    categories: list[dict[str, Any]], **fields: Any,
) -> Forecast:
    """Для worker-а. Предыдущие current-прогнозы на месяц становятся stale.
    Сумма категорий должна совпадать с общей точкой (FR-27, приёмка)."""
    if predicted_minor < 0 or any(c["predicted_minor"] < 0 for c in categories):
        raise ValidationFailed("Прогноз не может быть отрицательным")
    if categories and sum(c["predicted_minor"] for c in categories) != predicted_minor:
        raise ValidationFailed("Сумма прогнозов категорий должна равняться общему прогнозу")
    db.execute(update(Forecast).where(
        Forecast.household_id == household_id, Forecast.target_month == target_month,
        Forecast.status == ForecastStatus.CURRENT.value,
    ).values(status=ForecastStatus.STALE.value))
    fc = Forecast(id=uuid.uuid4(), household_id=household_id, target_month=target_month,
                  predicted_minor=predicted_minor, **fields)
    db.add(fc)
    db.flush()
    for c in categories:
        db.add(ForecastCategory(id=uuid.uuid4(), forecast_id=fc.id, **c))
    db.flush()
    return fc


def get_forecast(db: Session, ctx: RequestContext, month: str | date) -> ForecastView:
    """GET /forecasts?month=. Отсутствие данных — нормальное состояние (availability), а не нулевой прогноз (BR-10).
    Устаревшим считается результат, построенный на меньшей data_version, чем у семьи."""
    household, _ = authorize(db, ctx)
    month_d = parse_month(month)
    fc = db.execute(
        select(Forecast).where(Forecast.household_id == household.id, Forecast.target_month == month_d)
        .order_by(Forecast.generated_at.desc())
    ).scalars().first()

    if fc is None:
        availability = "insufficient_history" if count_complete_months(db, household.id) < MIN_HISTORY_MONTHS else "pending"
        return ForecastView(availability=availability, target_month=month_d)

    stale = fc.status == ForecastStatus.STALE.value or int(fc.data_version) < int(household.data_version)
    cats = db.execute(select(ForecastCategory).where(ForecastCategory.forecast_id == fc.id)).scalars().all()
    return ForecastView(
        availability="stale" if stale else "ready",
        target_month=month_d,
        predicted_minor=int(fc.predicted_minor),
        lower_minor=int(fc.lower_minor) if fc.lower_minor is not None else None,
        upper_minor=int(fc.upper_minor) if fc.upper_minor is not None else None,
        interval_level=float(fc.interval_level) if fc.interval_level is not None else None,
        history_start=fc.history_start, history_end=fc.history_end,
        model_version=fc.model_version, generated_at=fc.generated_at,
        categories=[ForecastCategoryOut.model_validate(c) for c in cats],
    )
