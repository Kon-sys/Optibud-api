"""/health/live и /health/ready (архитектура 14.3). Без префикса /v1."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.deps import get_db

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", operation_id="health_live")
def live():
    return {"status": "ok"}


@router.get("/ready", operation_id="health_ready")
def ready(response: Response, db: Session = Depends(get_db)):
    """Готовность определяется доступностью PostgreSQL (Ollama/push на неё не влияют)."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001
        response.status_code = 503
        return {"status": "unavailable"}
    return {"status": "ok"}
