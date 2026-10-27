
from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestContext:
    user_id: uuid.UUID
    household_id: uuid.UUID

    role: str | None = None
    request_id: str | None = None
