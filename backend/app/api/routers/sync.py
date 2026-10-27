"""Синхронизация (архитектура 8.2): push и pull."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_household_ctx
from app.core.context import RequestContext
from app.crud import sync as sync_crud
from app.schemas.sync import SyncOperationResult, SyncPullOut, SyncPushIn

router = APIRouter(prefix="/households/{h}/sync", tags=["sync"])


@router.post("/push", response_model=list[SyncOperationResult], operation_id="sync_push")
def push(body: SyncPushIn, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    """До 100 операций. Результат у каждой свой (accepted/replayed/conflict/rejected)."""
    results = sync_crud.push_operations(db, ctx, body.operations)
    db.commit()
    return results


@router.get("/pull", response_model=SyncPullOut, operation_id="sync_pull")
def pull(
    cursor: str | None = None, limit: int = Query(200, ge=1, le=500),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = sync_crud.pull_changes(db, ctx, cursor, limit)
    db.commit()
    return out
