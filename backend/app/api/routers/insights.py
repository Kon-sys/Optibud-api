"""Аналитика, аномалии, рекомендации, прогнозы (архитектура 7.7)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_household_ctx
from app.core.context import RequestContext
from app.crud import analytics as analytics_crud
from app.crud import insights as insights_crud
from app.schemas.auth import FeedbackOut
from app.schemas.common import Page
from app.schemas.insights import (
    AnomalyFeedbackIn, AnomalyOut, CategoryMetric, ForecastView, RecommendationFeedbackIn,
    RecommendationOut, SummarySnapshot,
)

router = APIRouter(prefix="/households/{h}", tags=["insights"])


@router.get("/analytics/summary", response_model=SummarySnapshot, operation_id="analytics_summary")
def summary(
    date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = analytics_crud.get_summary(db, ctx, date_from, date_to)
    db.commit()
    return out


@router.get("/analytics/categories", response_model=list[CategoryMetric], operation_id="analytics_categories")
def categories(
    date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = analytics_crud.get_category_metrics(db, ctx, date_from, date_to)
    db.commit()
    return out


@router.get("/forecasts", response_model=ForecastView, operation_id="forecasts_get")
def forecast(month: str, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = insights_crud.get_forecast(db, ctx, month)
    db.commit()
    return out


@router.get("/anomalies", response_model=Page[AnomalyOut], operation_id="anomalies_list")
def anomalies(
    status: Literal["active", "stale", "resolved"] | None = None, cursor: str | None = None,
    limit: int = Query(50, ge=1, le=100),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    items, next_cursor, has_more = insights_crud.list_anomalies(db, ctx, status=status, cursor=cursor, limit=limit)
    out = Page[AnomalyOut](items=items, next_cursor=next_cursor, has_more=has_more)
    db.commit()
    return out


@router.put("/anomalies/{anomaly_id}/feedback", response_model=FeedbackOut, operation_id="anomalies_feedback")
def anomaly_feedback(
    anomaly_id: uuid.UUID, body: AnomalyFeedbackIn,
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    fb = insights_crud.set_anomaly_feedback(db, ctx, anomaly_id, body.label)
    out = FeedbackOut(value=fb.label)
    db.commit()
    return out


@router.get("/recommendations", response_model=list[RecommendationOut], operation_id="recommendations_list")
def recommendations(
    status: Literal["active", "stale", "expired"] | None = "active",
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = [RecommendationOut.model_validate(r) for r in insights_crud.list_recommendations(db, ctx, status)]
    db.commit()
    return out


@router.put("/recommendations/{rec_id}/feedback", response_model=FeedbackOut, operation_id="recommendations_feedback")
def recommendation_feedback(
    rec_id: uuid.UUID, body: RecommendationFeedbackIn,
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    fb = insights_crud.set_recommendation_feedback(db, ctx, rec_id, body.action)
    out = FeedbackOut(value=fb.action)
    db.commit()
    return out
