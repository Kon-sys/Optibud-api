"""Операции (архитектура 7.4)."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_household_ctx, require_if_match, set_etag
from app.core.context import RequestContext
from app.crud import transaction as tx_crud
from app.schemas.transaction import (
    TransactionCreate, TransactionFilter, TransactionOut, TransactionPage, TransactionPatch,
)

router = APIRouter(prefix="/households/{h}/transactions", tags=["transactions"])


@router.get("", response_model=TransactionPage, operation_id="transactions_list")
def list_transactions(
    date_from: date | None = Query(default=None, alias="from"),
    date_to: date | None = Query(default=None, alias="to"),
    type: Literal["income", "expense", "refund", "transfer"] | None = None,
    category_id: uuid.UUID | None = None,
    author_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=120),
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    ctx: RequestContext = Depends(get_household_ctx),
    db: Session = Depends(get_db),
):
    flt = TransactionFilter(date_from=date_from, date_to=date_to, type=type, category_id=category_id, author_id=author_id, q=q)
    items, next_cursor, has_more, summary = tx_crud.list_transactions(db, ctx, flt, cursor=cursor, limit=limit)
    out = TransactionPage(
        items=[TransactionOut.model_validate(t) for t in items], next_cursor=next_cursor, has_more=has_more, summary=summary
    )
    db.commit()
    return out


@router.post("", status_code=201, response_model=TransactionOut, operation_id="transactions_create")
def create_transaction(
    body: TransactionCreate, response: Response,
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    """201 при создании; 200, если запись с этим id уже создана этим же пользователем (безопасный повтор).
    Идемпотентность обеспечивает стабильный UUID записи, созданный клиентом."""
    tx, created = tx_crud.create_transaction(db, ctx, body)
    out = TransactionOut.model_validate(tx)
    db.commit()
    response.status_code = 201 if created else 200
    set_etag(response, out.version)
    return out


@router.get("/{tx_id}", response_model=TransactionOut, operation_id="transactions_get")
def get_transaction(tx_id: uuid.UUID, response: Response, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = TransactionOut.model_validate(tx_crud.get_transaction(db, ctx, tx_id))
    db.commit()
    set_etag(response, out.version)
    return out


@router.patch("/{tx_id}", response_model=TransactionOut, operation_id="transactions_patch")
def patch_transaction(
    tx_id: uuid.UUID, body: TransactionPatch, response: Response, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = TransactionOut.model_validate(tx_crud.update_transaction(db, ctx, tx_id, body, version))
    db.commit()
    set_etag(response, out.version)
    return out


@router.delete("/{tx_id}", status_code=204, operation_id="transactions_delete")
def delete_transaction(
    tx_id: uuid.UUID, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    tx_crud.delete_transaction(db, ctx, tx_id, version)
    db.commit()
    return Response(status_code=204)
