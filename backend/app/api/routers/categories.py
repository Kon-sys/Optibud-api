"""Категории и правила категоризации (архитектура 7.4)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_household_ctx, require_if_match, set_etag
from app.core.context import RequestContext
from app.crud import category as cat
from app.schemas.category import (
    CategoryCreate, CategoryOut, CategoryPatch, CategoryRuleCreate, CategoryRuleOut, CategoryRulePatch,
)

router = APIRouter(prefix="/households/{h}", tags=["categories"])


@router.get("/categories", response_model=list[CategoryOut], operation_id="categories_list")
def list_categories(include_archived: bool = False, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = [CategoryOut.model_validate(c) for c in cat.list_categories(db, ctx, include_archived)]
    db.commit()
    return out


@router.post("/categories", status_code=201, response_model=CategoryOut, operation_id="categories_create")
def create_category(body: CategoryCreate, response: Response, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = CategoryOut.model_validate(cat.create_category(db, ctx, body))
    db.commit()
    set_etag(response, out.version)
    return out


@router.patch("/categories/{category_id}", response_model=CategoryOut, operation_id="categories_patch")
def patch_category(
    category_id: uuid.UUID, body: CategoryPatch, response: Response, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = CategoryOut.model_validate(cat.update_category(db, ctx, category_id, body, version))
    db.commit()
    set_etag(response, out.version)
    return out


@router.get("/category-rules", response_model=list[CategoryRuleOut], operation_id="category_rules_list")
def list_rules(ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = [CategoryRuleOut.model_validate(r) for r in cat.list_rules(db, ctx)]
    db.commit()
    return out


@router.post("/category-rules", status_code=201, response_model=CategoryRuleOut, operation_id="category_rules_create")
def create_rule(body: CategoryRuleCreate, response: Response, ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db)):
    out = CategoryRuleOut.model_validate(cat.create_rule(db, ctx, body))
    db.commit()
    set_etag(response, out.version)
    return out


@router.patch("/category-rules/{rule_id}", response_model=CategoryRuleOut, operation_id="category_rules_patch")
def patch_rule(
    rule_id: uuid.UUID, body: CategoryRulePatch, response: Response, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    out = CategoryRuleOut.model_validate(cat.update_rule(db, ctx, rule_id, body, version))
    db.commit()
    set_etag(response, out.version)
    return out


@router.delete("/category-rules/{rule_id}", status_code=204, operation_id="category_rules_delete")
def delete_rule(
    rule_id: uuid.UUID, version: int = Depends(require_if_match),
    ctx: RequestContext = Depends(get_household_ctx), db: Session = Depends(get_db),
):
    cat.delete_rule(db, ctx, rule_id, version)
    db.commit()
    return Response(status_code=204)
