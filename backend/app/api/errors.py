from __future__ import annotations

import logging
import uuid

from app.core.config import is_local
from app.core.errors import DomainError
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

logger = logging.getLogger("optibud.app.api")


def _rid(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def install(app: FastAPI) -> None:
    @app.middleware("http")
    async def common_headers(request: Request, call_next):
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = rid
        response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/v1"):
            response.headers["Cache-Control"] = "no-store"
        if not is_local():
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError):
        headers = {"Cache-Control": "no-store"}
        if exc.status_code == 401:
            headers["WWW-Authenticate"] = "Cookie"
        return JSONResponse(status_code=exc.status_code, content=exc.to_dict(_rid(request)), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        field_errors = [
            {"field": ".".join(str(p) for p in e["loc"] if p not in ("body", "query", "path", "header")),
             "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content={"code": "VALIDATION_ERROR", "message": "Некорректные данные запроса",
                     "request_id": _rid(request), "field_errors": field_errors},
        )

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):

        logger.exception("Необработанная ошибка request_id=%s", _rid(request))
        return JSONResponse(
            status_code=500,
            content={"code": "INTERNAL_ERROR", "message": "Внутренняя ошибка сервера",
                     "request_id": _rid(request), "field_errors": []},
        )
