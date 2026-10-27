
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from app.core.config import get_cursor_signing_key
from app.core.errors import ValidationFailed


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def encode_cursor(payload: dict[str, Any]) -> str:
    body = _b64e(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    sig = _b64e(hmac.new(get_cursor_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
    return f"{body}.{sig}"


def decode_cursor(token: str) -> dict[str, Any]:
    try:
        body, sig = token.split(".", 1)
        expected = _b64e(hmac.new(get_cursor_signing_key(), body.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            raise ValueError("bad signature")
        data = json.loads(_b64d(body))
        if not isinstance(data, dict):
            raise ValueError("bad payload")
        return data
    except Exception:
        raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")


def filters_hash(filters: dict[str, Any]) -> str:

    raw = json.dumps(filters, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
