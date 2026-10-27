
from __future__ import annotations

import os


def get_cursor_signing_key() -> bytes:

    key = os.getenv("CURSOR_SIGNING_KEY")
    if not key:
        if os.getenv("APP_ENV", "local") in ("staging", "production"):
            raise RuntimeError("CURSOR_SIGNING_KEY не задан")
        key = "dev-only-cursor-key-change-me"
    return key.encode("utf-8")


def app_env() -> str:
    return os.getenv("APP_ENV", "local")


def is_local() -> bool:
    return app_env() == "local"


def public_origin() -> str | None:

    return os.getenv("PUBLIC_ORIGIN") or None


def session_cookie_name() -> str:

    return "optibud_session" if is_local() else "__Host-optibud_session"


def cookie_secure() -> bool:
    return not is_local()


def get_csrf_key() -> bytes:
    key = os.getenv("CSRF_SIGNING_KEY")
    if not key:
        if app_env() in ("staging", "production"):
            raise RuntimeError("CSRF_SIGNING_KEY не задан")
        key = "dev-only-csrf-key-change-me"
    return key.encode("utf-8")


def email_provider() -> str:
    return os.getenv("EMAIL_PROVIDER", "console")
