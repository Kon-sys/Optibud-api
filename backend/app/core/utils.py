
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from app.core.errors import ValidationFailed, field_error

DEFAULT_TIMEZONE = "Europe/Minsk"
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime | None) -> datetime | None:

    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(raw: str, field: str = "email") -> str:

    value = (raw or "").strip().lower()
    if len(value) > 254 or not _EMAIL_RE.match(value):
        raise ValidationFailed(
            "Некорректный адрес электронной почты",
            field_errors=[field_error(field, "Некорректный адрес электронной почты")],
        )
    return value


def today_in(tz_name: str = DEFAULT_TIMEZONE) -> date:

    return datetime.now(ZoneInfo(tz_name)).date()


def first_day_of_month(value: date) -> date:
    return value.replace(day=1)


def last_day_of_month(value: date) -> date:
    return value.replace(day=calendar.monthrange(value.year, value.month)[1])


def parse_month(value: str | date) -> date:

    if isinstance(value, date):
        return value.replace(day=1)
    try:
        year, month = value.split("-")
        return date(int(year), int(month), 1)
    except (ValueError, AttributeError):
        raise ValidationFailed(
            "Месяц должен быть в формате YYYY-MM",
            field_errors=[field_error("month", "Ожидается формат YYYY-MM")],
        )


def add_months(value: date, months: int) -> date:

    index = value.year * 12 + (value.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def months_remaining_inclusive(today: date, target: date) -> int:

    return (target.year - today.year) * 12 + (target.month - today.month) + 1


def escape_like(value: str) -> str:

    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
