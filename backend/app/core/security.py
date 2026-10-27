
from __future__ import annotations

import hashlib
import hmac
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.errors import ValidationFailed, field_error


_hasher = PasswordHasher()
_DUMMY_HASH: str | None = None

PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128


def validate_password_policy(password: str, field: str = "password") -> None:

    if not (PASSWORD_MIN_LENGTH <= len(password) <= PASSWORD_MAX_LENGTH):
        raise ValidationFailed(
            "Пароль должен содержать от 12 до 128 символов",
            field_errors=[field_error(field, "Длина пароля — от 12 до 128 символов")],
        )


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_needs_rehash(password_hash: str) -> bool:
    return _hasher.check_needs_rehash(password_hash)


def burn_password_check(password: str) -> None:

    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))
    verify_password(_DUMMY_HASH, password)


def new_token() -> str:

    return secrets.token_urlsafe(32)


def token_hash(raw_token: str) -> str:

    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def safe_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))
