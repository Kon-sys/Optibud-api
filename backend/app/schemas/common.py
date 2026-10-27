from __future__ import annotations

from typing import Annotated, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_AMOUNT_MINOR = 999_999_999_999

# Деньги всегда целым числом копеек (ADR-003)
AmountMinor = Annotated[int, Field(ge=1, le=MAX_AMOUNT_MINOR)]
Currency = Annotated[str, StringConstraints(pattern="^BYN$")]
Trimmed = Annotated[str, StringConstraints(strip_whitespace=True)]

T = TypeVar("T")


class CommandModel(BaseModel):


    model_config = ConfigDict(extra="forbid")


class OutModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Page(BaseModel, Generic[T]):
    items: list[T]
    next_cursor: str | None = None
    has_more: bool = False
