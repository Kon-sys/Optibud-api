from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.schemas.common import CommandModel, OutModel, Trimmed


class HouseholdCreate(CommandModel):
    name: Trimmed = Field(min_length=1, max_length=80)
    adults_count: int = Field(ge=1, le=10)
    children_count: int = Field(ge=0, le=20)
    region_code: str | None = Field(default=None, max_length=50)
    income_band: str | None = Field(default=None, max_length=50)


class HouseholdPatch(CommandModel):
    name: Trimmed | None = Field(default=None, min_length=1, max_length=80)
    adults_count: int | None = Field(default=None, ge=1, le=10)
    children_count: int | None = Field(default=None, ge=0, le=20)
    region_code: str | None = Field(default=None, max_length=50)
    income_band: str | None = Field(default=None, max_length=50)


class HouseholdOut(OutModel):
    id: uuid.UUID
    name: str
    adults_count: int
    children_count: int
    region_code: str | None
    income_band: str | None
    currency: str
    timezone: str
    version: int
    data_version: int
    membership_version: int


class MemberOut(OutModel):
    id: uuid.UUID
    household_id: uuid.UUID
    user_id: uuid.UUID
    display_name: str
    role: str
    joined_at: datetime


class InvitationCreate(CommandModel):
    email: str = Field(max_length=254)


class InvitationOut(OutModel):


    id: uuid.UUID
    household_id: uuid.UUID
    email_normalized: str
    status: str
    expires_at: datetime
    created_at: datetime


class TransferOwnerIn(CommandModel):
    target_member_id: uuid.UUID
    password: str = Field(max_length=256)
