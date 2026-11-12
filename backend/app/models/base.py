from sqlalchemy import Column, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    __abstract__ = True


class TimestampMixin:
    """created_at/updated_at для моделей, которым не нужны специальные дефолты."""

    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)


# Postgres-only проект (psycopg) — используем JSONB ради индексируемости.
JSONType = JSONB


def in_list(column: str, enum_cls) -> str:
    """SQL-текст для CheckConstraint: column IN ('val1', 'val2', ...) по значениям StrEnum."""
    values = ", ".join(f"'{e.value}'" for e in enum_cls)
    return f"{column} IN ({values})"
