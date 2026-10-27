"""Бюджеты, цели, движения по целям, полнота истории (архитектура 7.5, 7.6)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_household_ctx, if_match, require_if_match, set_etag
from app.core.context import RequestContext
from app.crud import budget as budget_crud
from app.crud import goal as goal_crud
from app.crud import history as history_crud
from app.schemas.budget import BudgetOut, BudgetUpsert
from app.schemas.common import Page
from app.schemas.goal import (
    ContributionCreate, ContributionOut, ContributionPatch, GoalCreate, GoalOut, GoalPatch,
)
from app.schemas.insights import HistoryMonthOut, HistoryMonthSetIn

router = APIRouter(prefix="/households/{h}", tags=["planning"])


# ------------------------------------------------------------------ бюджеты
@router.get("/budgets/{month}", response_model=BudgetOut, operation_id="budgets_get")
def get_budget(month: str, response: Response, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = budget_crud.budget_view(db, budget_crud.get_budget(db, ctx, month))
    db.commit()
    set_etag(response, out.version)
    return out


@router.put("/budgets/{month}", response_model=BudgetOut, operation_id="budgets_put")
def put_budget(
    month: str, body: BudgetUpsert, response: Response,
    version: int | None = Depends(if_match),
    if_none_match: str | None = Header(default=None),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    """Существующий месяц: If-Match. Создание нового: If-None-Match: *."""
    budget = budget_crud.upsert_budget(
        db, ctx, month, body, expected_version=version, create_only=(if_none_match or "").strip() == "*"
    )
    out = budget_crud.budget_view(db, budget)
    db.commit()
    set_etag(response, out.version)
    return out


# ------------------------------------------------------------------ цели
@router.get("/goals", response_model=Page[GoalOut], operation_id="goals_list")
def list_goals(
    status: str | None = None, cursor: str | None = None, limit: int = Query(50, ge=1, le=100),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    items, next_cursor, has_more = goal_crud.list_goals(db, ctx, status=status, cursor=cursor, limit=limit)
    out = Page[GoalOut](items=[goal_crud.goal_view(db, g) for g in items], next_cursor=next_cursor, has_more=has_more)
    db.commit()
    return out


@router.post("/goals", status_code=201, response_model=GoalOut, operation_id="goals_create")
def create_goal(body: GoalCreate, response: Response, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = goal_crud.goal_view(db, goal_crud.create_goal(db, ctx, body))
    db.commit()
    set_etag(response, out.version)
    return out


@router.patch("/goals/{goal_id}", response_model=GoalOut, operation_id="goals_patch")
def patch_goal(
    goal_id: uuid.UUID, body: GoalPatch, response: Response, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = goal_crud.goal_view(db, goal_crud.update_goal(db, ctx, goal_id, body, version))
    db.commit()
    set_etag(response, out.version)
    return out


@router.get("/goals/{goal_id}/contributions", response_model=Page[ContributionOut], operation_id="contributions_list")
def list_contributions(
    goal_id: uuid.UUID, cursor: str | None = None, limit: int = Query(50, ge=1, le=100),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    items, next_cursor, has_more = goal_crud.list_contributions(db, ctx, goal_id, cursor=cursor, limit=limit)
    out = Page[ContributionOut](
        items=[ContributionOut.model_validate(c) for c in items], next_cursor=next_cursor, has_more=has_more
    )
    db.commit()
    return out


@router.post("/goals/{goal_id}/contributions", status_code=201, response_model=ContributionOut, operation_id="contributions_create")
def add_contribution(
    goal_id: uuid.UUID, body: ContributionCreate, response: Response,
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    contribution, created = goal_crud.add_contribution(db, ctx, goal_id, body)
    out = ContributionOut.model_validate(contribution)
    db.commit()
    response.status_code = 201 if created else 200
    set_etag(response, out.version)
    return out


@router.patch("/goals/{goal_id}/contributions/{contribution_id}", response_model=ContributionOut, operation_id="contributions_patch")
def patch_contribution(
    goal_id: uuid.UUID, contribution_id: uuid.UUID, body: ContributionPatch, response: Response,
    version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = ContributionOut.model_validate(goal_crud.update_contribution(db, ctx, goal_id, contribution_id, body, version))
    db.commit()
    set_etag(response, out.version)
    return out


@router.delete("/goals/{goal_id}/contributions/{contribution_id}", status_code=204, operation_id="contributions_delete")
def delete_contribution(
    goal_id: uuid.UUID, contribution_id: uuid.UUID, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    goal_crud.delete_contribution(db, ctx, goal_id, contribution_id, version)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------------ полнота истории
@router.put("/history-months/{month}", response_model=HistoryMonthOut, operation_id="history_months_put")
def put_history_month(
    month: str, body: HistoryMonthSetIn, response: Response, version: int | None = Depends(if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = HistoryMonthOut.model_validate(history_crud.set_history_month(db, ctx, month, body.completeness, version))
    db.commit()
    set_etag(response, out.version)
    return out
