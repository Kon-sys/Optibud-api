from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.schemas.common import CommandModel, OutModel, Trimmed


class CategoryCreate(CommandModel):
    name: Trimmed = Field(min_length=1, max_length=80)
    parent_id: uuid.UUID
    type: Literal["income", "expense"]


class CategoryPatch(CommandModel):
    name: Trimmed | None = Field(default=None, min_length=1, max_length=80)
    is_archived: bool | None = None


class SystemCategoryCreate(CommandModel):
    system_code: str = Field(min_length=1, max_length=50)
    name: Trimmed = Field(min_length=1, max_length=80)
    type: Literal["income", "expense"]


class CategoryOut(OutModel):
    id: uuid.UUID
    household_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    system_code: str | None
    name: str
    type: str
    is_archived: bool
    version: int


class CategoryRuleCreate(CommandModel):
    match_type: Literal["equals", "contains", "starts_with"]
    pattern: Trimmed = Field(min_length=1, max_length=120)
    category_id: uuid.UUID
    priority: int = Field(default=0, ge=0, le=1000)


class CategoryRulePatch(CommandModel):
    match_type: Literal["equals", "contains", "starts_with"] | None = None
    pattern: Trimmed | None = Field(default=None, min_length=1, max_length=120)
    category_id: uuid.UUID | None = None
    priority: int | None = Field(default=None, ge=0, le=1000)


class CategoryRuleOut(OutModel):
    id: uuid.UUID
    household_id: uuid.UUID | None
    match_type: str
    pattern: str
    category_id: uuid.UUID
    priority: int
    version: int
