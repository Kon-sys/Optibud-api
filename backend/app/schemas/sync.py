from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import CommandModel


class SyncOperationIn(CommandModel):
    operation_id: uuid.UUID
    entity_type: Literal["transaction"]
    entity_id: uuid.UUID
    action: Literal["create", "update", "delete"]
    base_version: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class SyncPushIn(CommandModel):
    operations: list[SyncOperationIn] = Field(max_length=100)


class SyncOperationResult(BaseModel):
    operation_id: uuid.UUID
    status: Literal["accepted", "replayed", "conflict", "rejected"]
    server_version: int | None = None
    error: dict[str, Any] | None = None


class ChangeOut(BaseModel):
    seq: int
    entity_type: str
    entity_id: uuid.UUID
    action: str
    entity_version: int
    payload: dict[str, Any] | None


class SyncPullOut(BaseModel):
    changes: list[ChangeOut]
    next_cursor: str
    has_more: bool
    server_time: datetime
