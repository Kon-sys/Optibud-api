from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from pydantic import Field, StringConstraints

from app.schemas.common import CommandModel, OutModel

DisplayName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]


class RegisterIn(CommandModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=1, max_length=256)  # политика 12–128 проверяется в security
    terms_version: str = Field(min_length=1, max_length=50)


class LoginIn(CommandModel):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)
    device_label: str | None = Field(default=None, max_length=120)


class ProfilePatch(CommandModel):
    display_name: DisplayName | None = None
    locale: str | None = Field(default=None, max_length=10)
    preferences: dict[str, Any] | None = None


class UserSummary(OutModel):
    id: uuid.UUID
    display_name: str


class SessionSummary(OutModel):
    session_id: uuid.UUID
    idle_expires_at: datetime
    absolute_expires_at: datetime


class SessionListItem(OutModel):
    id: uuid.UUID
    device_label: str | None
    created_at: datetime
    last_seen_at: datetime
    current: bool = False


class MembershipOut(OutModel):
    id: uuid.UUID
    household_id: uuid.UUID
    user_id: uuid.UUID
    role: str
    joined_at: datetime


class ProfileOut(OutModel):
    id: uuid.UUID
    email: str
    display_name: str
    locale: str
    preferences: dict[str, Any]
    version: int
    membership: MembershipOut | None = None
