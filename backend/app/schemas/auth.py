from __future__ import annotations

from pydantic import Field

from app.schemas.common import CommandModel
from app.schemas.user import SessionSummary, UserSummary
from app.schemas.common import OutModel


class TokenIn(CommandModel):
    token: str = Field(min_length=10, max_length=200)


class PasswordResetIn(CommandModel):
    email: str = Field(max_length=254)


class PasswordResetConfirmIn(CommandModel):
    token: str = Field(min_length=10, max_length=200)
    new_password: str = Field(max_length=256)


class PasswordIn(CommandModel):
    password: str = Field(max_length=256)


class EmailChangeIn(CommandModel):
    new_email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class LoginOut(OutModel):
    user: UserSummary
    session: SessionSummary


class CsrfOut(OutModel):
    csrf_token: str


class AcceptedOut(OutModel):
    status: str = "accepted"


class FeedbackOut(OutModel):
    value: str
