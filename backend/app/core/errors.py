
from __future__ import annotations

from typing import Any


class DomainError(Exception):
    status_code: int = 400
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str = "Некорректный запрос",
        *,
        code: str | None = None,
        field_errors: list[dict[str, str]] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code
        self.field_errors = field_errors or []
        self.extra = extra or {}

    def to_dict(self, request_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "request_id": request_id,
            "field_errors": self.field_errors,
        }
        body.update(self.extra)
        return body


class AuthenticationFailed(DomainError):

    status_code = 401
    code = "UNAUTHENTICATED"


class AccessDenied(DomainError):

    status_code = 403
    code = "ACCESS_DENIED"


class NotFound(DomainError):

    status_code = 404
    code = "NOT_FOUND"


class BusinessConflict(DomainError):

    status_code = 409
    code = "CONFLICT"


class VersionConflict(BusinessConflict):

    code = "VERSION_CONFLICT"

    def __init__(
        self,
        message: str = "Запись изменена на другом устройстве",
        *,
        current_version: int,
        current_record: Any | None = None,
    ) -> None:
        extra: dict[str, Any] = {"current_version": current_version}
        if current_record is not None:
            extra["current_record"] = current_record
        super().__init__(message, extra=extra)


class IdempotencyKeyReused(BusinessConflict):
    code = "IDEMPOTENCY_KEY_REUSED"


class CursorExpired(DomainError):

    status_code = 410
    code = "SYNC_CURSOR_EXPIRED"


class PreconditionRequired(DomainError):

    status_code = 428
    code = "PRECONDITION_REQUIRED"


class ValidationFailed(DomainError):

    status_code = 422
    code = "VALIDATION_ERROR"


def field_error(field: str, message: str) -> dict[str, str]:
    return {"field": field, "message": message}
