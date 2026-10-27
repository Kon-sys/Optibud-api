
from __future__ import annotations

import logging
from typing import Any, Protocol

from app.core.config import email_provider, is_local, public_origin

logger = logging.getLogger("optibud.email")

LINK_PATHS = {
    "verify_email": "/verify-email?token={token}",
    "password_reset": "/password-reset?token={token}",
    "email_change": "/confirm-email-change?token={token}",
    "invitation": "/invitation?token={token}",
}


class EmailGateway(Protocol):
    def send(self, template: str, to: str, params: dict[str, Any]) -> None: ...


class ConsoleEmailGateway:
    def send(self, template: str, to: str, params: dict[str, Any]) -> None:
        if not is_local():
            raise RuntimeError("ConsoleEmailGateway допустим только в local; настройте EMAIL_PROVIDER")
        path = LINK_PATHS.get(template, "/{token}").format(token=params.get("token", ""))
        logger.info("[DEV EMAIL] template=%s to=%s link=%s%s", template, to, public_origin() or "http://localhost:5173", path)


def get_gateway() -> EmailGateway:
    if email_provider() == "console":
        return ConsoleEmailGateway()
    raise RuntimeError(f"Неизвестный EMAIL_PROVIDER: {email_provider()}")


def send_email(template: str, to: str, params: dict[str, Any]) -> None:

    try:
        get_gateway().send(template, to, params)
    except Exception:  # noqa: BLE001
        logger.exception("Не удалось отправить письмо template=%s", template)
