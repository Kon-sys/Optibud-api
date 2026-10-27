"""Протокол синхронизации (архитектура, раздел 8): push с идемпотентностью и pull по курсору.

Снимки (POST /sync/snapshots) в этот модуль не входят — они строятся отдельным
сервисом в REPEATABLE READ и материализуются в объектное хранилище."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.cursor import decode_cursor, encode_cursor
from app.core.errors import (
    CursorExpired,
    DomainError,
    IdempotencyKeyReused,
    PreconditionRequired,
    ValidationFailed,
    VersionConflict,
)
from app.core.utils import utcnow
from app.crud._common import authorize
from app.crud.transaction import create_transaction, delete_transaction, update_transaction
from app.models import ChangeLog, SyncOperation
from app.schemas.sync import ChangeOut, SyncOperationIn, SyncOperationResult, SyncPullOut
from app.schemas.transaction import TransactionCreate, TransactionPatch

MAX_PUSH = 100
DEFAULT_PULL = 200
MAX_PULL = 500
RETENTION = timedelta(days=30)


def request_hash(op: SyncOperationIn) -> str:
    """Хэш нормализованного тела; повтор с другим телом = IDEMPOTENCY_KEY_REUSED (п. 8.5)."""
    body = {
        "entity_type": op.entity_type, "entity_id": str(op.entity_id), "action": op.action,
        "base_version": op.base_version, "payload": op.payload,
    }
    return hashlib.sha256(json.dumps(body, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()


def _apply(db: Session, ctx: RequestContext, op: SyncOperationIn) -> SyncOperationResult:
    if op.action == "create":
        data = TransactionCreate.model_validate({**op.payload, "id": str(op.entity_id)})
        tx, created = create_transaction(db, ctx, data, correlation_id=op.operation_id)
        return SyncOperationResult(
            operation_id=op.operation_id, status="accepted" if created else "replayed", server_version=int(tx.version)
        )
    if op.base_version is None:
        raise PreconditionRequired("Для update/delete необходима base_version")
    if op.action == "update":
        patch = TransactionPatch.model_validate(op.payload)
        tx = update_transaction(db, ctx, op.entity_id, patch, op.base_version, correlation_id=op.operation_id)
    else:
        tx = delete_transaction(db, ctx, op.entity_id, op.base_version, correlation_id=op.operation_id)
    return SyncOperationResult(operation_id=op.operation_id, status="accepted", server_version=int(tx.version))


def push_operations(db: Session, ctx: RequestContext, operations: list[SyncOperationIn]) -> list[SyncOperationResult]:
    """POST /sync/push. Каждая операция выполняется в SAVEPOINT и получает собственный результат.

    Права проверяются ДО возврата сохранённых ответов: исключённый участник не прочитает старые данные.
    Автоматического «last write wins» для денег нет: расхождение версии -> status=conflict."""
    if len(operations) > MAX_PUSH:
        raise ValidationFailed("Не более 100 операций за запрос", code="TOO_MANY_OPERATIONS")
    authorize(db, ctx)

    results: list[SyncOperationResult] = []
    for op in operations:
        digest = request_hash(op)
        prior = db.execute(
            select(SyncOperation).where(
                SyncOperation.user_id == ctx.user_id,
                SyncOperation.household_id == ctx.household_id,
                SyncOperation.operation_id == op.operation_id,
            )
        ).scalar_one_or_none()
        if prior is not None:
            if prior.request_hash != digest:
                err = IdempotencyKeyReused("Ключ идемпотентности использован с другим телом")
                results.append(SyncOperationResult(operation_id=op.operation_id, status="rejected", error=err.to_dict()))
            else:
                stored = dict(prior.result)
                stored["status"] = "replayed"
                results.append(SyncOperationResult.model_validate(stored))
            continue

        try:
            with db.begin_nested():
                result = _apply(db, ctx, op)
        except VersionConflict as exc:
            result = SyncOperationResult(
                operation_id=op.operation_id, status="conflict",
                server_version=exc.extra.get("current_version"), error=exc.to_dict(),
            )
        except DomainError as exc:
            result = SyncOperationResult(operation_id=op.operation_id, status="rejected", error=exc.to_dict())
        except ValidationError as exc:
            result = SyncOperationResult(
                operation_id=op.operation_id, status="rejected",
                error={"code": "VALIDATION_ERROR", "message": "Некорректные данные операции",
                       "field_errors": [{"field": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]},
            )

        db.add(SyncOperation(
            id=uuid.uuid4(), user_id=ctx.user_id, household_id=ctx.household_id, operation_id=op.operation_id,
            request_hash=digest, result=result.model_dump(mode="json"),
        ))
        db.flush()
        results.append(result)
    return results


def pull_changes(db: Session, ctx: RequestContext, cursor: str | None = None, limit: int = DEFAULT_PULL) -> SyncPullOut:
    """GET /sync/pull. Курсор подписан и привязан к семье; журнал хранится 30 дней,
    просроченный курсор -> 410 SYNC_CURSOR_EXPIRED (нужен новый снимок)."""
    household, _ = authorize(db, ctx)
    limit = max(1, min(int(limit or DEFAULT_PULL), MAX_PULL))

    last_seq = 0
    if cursor:
        data = decode_cursor(cursor)
        if data.get("h") != str(household.id) or not isinstance(data.get("s"), int):
            raise ValidationFailed("Недействительный курсор", code="INVALID_CURSOR")
        last_seq = data["s"]

    min_seq = db.execute(
        select(func.min(ChangeLog.seq)).where(ChangeLog.household_id == household.id)
    ).scalar_one()
    if min_seq is not None and int(min_seq) > last_seq + 1:
        raise CursorExpired("Курсор синхронизации просрочен: загрузите новый снимок")

    rows = list(db.execute(
        select(ChangeLog).where(ChangeLog.household_id == household.id, ChangeLog.seq > last_seq)
        .order_by(ChangeLog.seq).limit(limit + 1)
    ).scalars().all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    new_seq = int(rows[-1].seq) if rows else last_seq
    return SyncPullOut(
        changes=[
            ChangeOut(seq=int(r.seq), entity_type=r.entity_type, entity_id=r.entity_id, action=r.action,
                      entity_version=int(r.entity_version), payload=r.payload)
            for r in rows
        ],
        next_cursor=encode_cursor({"h": str(household.id), "s": new_seq, "m": int(household.membership_version)}),
        has_more=has_more,
        server_time=utcnow(),
    )


def prune_sync_data(db: Session) -> dict[str, int]:
    """Плановая очистка (scheduler): change_log и sync_operations старше 30 дней."""
    border = utcnow() - RETENTION
    a = db.execute(delete(ChangeLog).where(ChangeLog.created_at < border))
    b = db.execute(delete(SyncOperation).where(SyncOperation.processed_at < border))
    return {"change_log": int(a.rowcount or 0), "sync_operations": int(b.rowcount or 0)}
