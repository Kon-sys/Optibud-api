"""Регистрация, вход, профиль, смена email/пароля, удаление аккаунта (FR-01…FR-05, DR-12)."""
from __future__ import annotations

import json
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from app.core.errors import (
    AccessDenied,
    AuthenticationFailed,
    BusinessConflict,
    NotFound,
    ValidationFailed,
    field_error,
)
from app.core.security import (
    burn_password_check,
    hash_password,
    new_token,
    password_needs_rehash,
    token_hash,
    validate_password_policy,
    verify_password,
)
from app.core.utils import as_utc, normalize_email, utcnow
from app.crud._common import (
    add_audit,
    add_outbox,
    ensure_version,
    get_active_membership,
    require_version,
    unique_guard,
)
from app.crud.session import revoke_all_sessions
from app.models import (
    AnomalyFeedback,
    AuditEvent,
    Consent,
    GoalContribution,
    Household,
    HistoryMonth,
    Invitation,
    Notification,
    RecommendationFeedback,
    SyncOperation,
    Transaction,
    User,
    UserSession,
    UserToken,
)
from app.models.enums import MemberRole, MemberStatus, TokenPurpose, UserStatus
from app.schemas.user import ProfilePatch

TOKEN_TTL = {
    TokenPurpose.VERIFY_EMAIL.value: timedelta(hours=24),
    TokenPurpose.PASSWORD_RESET.value: timedelta(minutes=30),
    TokenPurpose.EMAIL_CHANGE.value: timedelta(hours=24),
}
SUPPORTED_LOCALES = {"ru"}  # первая версия — только русский
DELETED_USER_NAME = "Удалённый участник"


# --------------------------------------------------------------------------- #
# Токены
# --------------------------------------------------------------------------- #
def _issue_token(db: Session, user_id: uuid.UUID, purpose: str, payload: dict[str, Any] | None = None) -> str:
    """Выпускает одноразовый токен; предыдущие неиспользованные токены этой цели аннулируются."""
    now = utcnow()
    db.execute(
        update(UserToken)
        .where(UserToken.user_id == user_id, UserToken.purpose == purpose, UserToken.used_at.is_(None))
        .values(used_at=now)
    )
    raw = new_token()
    db.add(
        UserToken(
            id=uuid.uuid4(),
            user_id=user_id,
            purpose=purpose,
            token_hash=token_hash(raw),
            payload=payload,
            expires_at=now + TOKEN_TTL[purpose],
        )
    )
    db.flush()
    return raw


def _consume_token(db: Session, raw: str, purpose: str) -> UserToken:
    """Токен одноразовый: повторное использование и просроченный токен отклоняются."""
    token = db.execute(
        select(UserToken)
        .where(UserToken.token_hash == token_hash(raw), UserToken.purpose == purpose)
        .with_for_update()
    ).scalar_one_or_none()
    now = utcnow()
    if token is None or token.used_at is not None or as_utc(token.expires_at) <= now:
        raise ValidationFailed("Ссылка недействительна или устарела", code="INVALID_TOKEN")
    token.used_at = now
    return token


# --------------------------------------------------------------------------- #
# Чтение
# --------------------------------------------------------------------------- #
def get_user(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFound("Пользователь не найден")
    return user


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email_normalized == normalize_email(email))).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Регистрация и вход
# --------------------------------------------------------------------------- #
def register_user(
    db: Session, *, email: str, password: str, terms_version: str, display_name: str | None = None
) -> tuple[User | None, str | None]:
    """FR-01. Возвращает (user, raw_token) для отправки письма подтверждения.

    Если адрес уже занят — (None, None): HTTP-слой отвечает тем же нейтральным 202,
    чтобы не раскрывать существование аккаунта (п. 7.2).
    """
    email_n = normalize_email(email)
    validate_password_policy(password)
    if db.execute(select(User.id).where(User.email_normalized == email_n)).first() is not None:
        return None, None

    name = (display_name or email_n.split("@")[0]).strip()[:80] or "Пользователь"
    user = User(
        id=uuid.uuid4(),
        email_normalized=email_n,
        display_name=name,
        password_hash=hash_password(password),
        status=UserStatus.PENDING.value,
        locale="ru",
        notification_preferences={},
        terms_version=terms_version,
        terms_accepted_at=utcnow(),
        version=1,
    )
    try:
        with unique_guard(db, "EMAIL_TAKEN", "Адрес уже используется"):
            db.add(user)
    except BusinessConflict:
        return None, None  # гонка двух регистраций: вторая тоже нейтральна

    raw = _issue_token(db, user.id, TokenPurpose.VERIFY_EMAIL.value)
    add_audit(db, actor_id=user.id, household_id=None, action="user.registered", target_type="user", target_id=user.id)
    return user, raw


def verify_email(db: Session, raw_token: str) -> User:
    """POST /auth/verify-email."""
    token = _consume_token(db, raw_token, TokenPurpose.VERIFY_EMAIL.value)
    user = get_user(db, token.user_id)
    if user.status == UserStatus.PENDING.value:
        user.status = UserStatus.ACTIVE.value
        user.verified_at = utcnow()
        user.version = int(user.version) + 1
    add_audit(db, actor_id=user.id, household_id=None, action="user.email_verified", target_type="user", target_id=user.id)
    db.flush()
    return user


def authenticate(db: Session, email: str, password: str) -> User:
    """FR-01/FR-03: проверка пароля. Ошибка одинакова для неизвестного адреса и неверного пароля.

    Ограничение частоты (5 попыток / 15 минут) реализуется отдельно (Redis, см. архитектуру 3.2).
    """
    try:
        email_n: str | None = normalize_email(email)
    except ValidationFailed:
        email_n = None
    user = None
    if email_n is not None:
        user = db.execute(select(User).where(User.email_normalized == email_n)).scalar_one_or_none()
    if user is None:
        burn_password_check(password)  # выравниваем время ответа
        raise AuthenticationFailed("Неверный адрес или пароль", code="INVALID_CREDENTIALS")
    if not verify_password(user.password_hash, password):
        raise AuthenticationFailed("Неверный адрес или пароль", code="INVALID_CREDENTIALS")
    if user.status == UserStatus.PENDING.value or user.verified_at is None:
        raise AuthenticationFailed("Подтвердите адрес электронной почты", code="EMAIL_NOT_VERIFIED")
    if user.status != UserStatus.ACTIVE.value:
        raise AuthenticationFailed("Учётная запись недоступна", code="ACCOUNT_DISABLED")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


# --------------------------------------------------------------------------- #
# Восстановление пароля
# --------------------------------------------------------------------------- #
def request_password_reset(db: Session, email: str) -> tuple[User | None, str | None]:
    """POST /auth/password-reset. (None, None), если адреса нет: ответ клиенту всегда 202."""
    try:
        email_n = normalize_email(email)
    except ValidationFailed:
        return None, None
    user = db.execute(select(User).where(User.email_normalized == email_n)).scalar_one_or_none()
    if user is None or user.status != UserStatus.ACTIVE.value:
        return None, None
    return user, _issue_token(db, user.id, TokenPurpose.PASSWORD_RESET.value)


def confirm_password_reset(db: Session, raw_token: str, new_password: str) -> User:
    """FR-02: ссылка одноразовая; после смены пароля все сеансы отзываются."""
    validate_password_policy(new_password, field="new_password")
    token = _consume_token(db, raw_token, TokenPurpose.PASSWORD_RESET.value)
    user = get_user(db, token.user_id)
    user.password_hash = hash_password(new_password)
    user.version = int(user.version) + 1
    revoke_all_sessions(db, user.id)
    add_audit(db, actor_id=user.id, household_id=None, action="user.password_reset", target_type="user", target_id=user.id)
    db.flush()
    return user


# --------------------------------------------------------------------------- #
# Профиль
# --------------------------------------------------------------------------- #
def update_profile(db: Session, user_id: uuid.UUID, patch: ProfilePatch, expected_version: int | None) -> User:
    """PATCH /profile (If-Match). Email здесь не меняется — только через подтверждение."""
    expected = require_version(expected_version)
    user = db.execute(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("Пользователь не найден")
    ensure_version(int(user.version), expected)

    data = patch.model_dump(exclude_unset=True)
    if "display_name" in data and data["display_name"] is not None:
        user.display_name = data["display_name"]
    if "locale" in data and data["locale"] is not None:
        if data["locale"] not in SUPPORTED_LOCALES:
            raise ValidationFailed(field_errors=[field_error("locale", "Язык не поддерживается")])
        user.locale = data["locale"]
    if "preferences" in data and data["preferences"] is not None:
        if len(json.dumps(data["preferences"], ensure_ascii=False)) > 4096:
            raise ValidationFailed(field_errors=[field_error("preferences", "Слишком большой объём настроек")])
        user.notification_preferences = data["preferences"]
    user.version = int(user.version) + 1
    db.flush()
    return user


def request_email_change(db: Session, user_id: uuid.UUID, new_email: str, password: str) -> str | None:
    """POST /profile/email-change. Токен для письма на НОВЫЙ адрес; None, если адрес занят
    (клиенту всё равно возвращается 202)."""
    user = get_user(db, user_id)
    if not verify_password(user.password_hash, password):
        raise AccessDenied("Неверный пароль", code="INVALID_PASSWORD")
    email_n = normalize_email(new_email, field="new_email")
    if email_n == user.email_normalized:
        raise ValidationFailed(field_errors=[field_error("new_email", "Адрес совпадает с текущим")])
    if db.execute(select(User.id).where(User.email_normalized == email_n)).first() is not None:
        return None
    return _issue_token(db, user.id, TokenPurpose.EMAIL_CHANGE.value, payload={"new_email": email_n})


def confirm_email_change(db: Session, raw_token: str) -> User:
    """Недостоверный email не становится основным до подтверждения (FR-04)."""
    token = _consume_token(db, raw_token, TokenPurpose.EMAIL_CHANGE.value)
    user = get_user(db, token.user_id)
    new_email = (token.payload or {}).get("new_email")
    if not new_email:
        raise ValidationFailed("Ссылка недействительна", code="INVALID_TOKEN")
    with unique_guard(db, "EMAIL_TAKEN", "Адрес уже используется"):
        user.email_normalized = new_email
        user.version = int(user.version) + 1
    add_audit(db, actor_id=user.id, household_id=None, action="user.email_changed", target_type="user", target_id=user.id)
    return user


# --------------------------------------------------------------------------- #
# Удаление аккаунта (DR-12, BR-12)
# --------------------------------------------------------------------------- #
def request_account_deletion(db: Session, user_id: uuid.UUID, password: str) -> User:
    """POST /profile/deletion. Сразу блокирует вход и отзывает сеансы.

    Владелец сначала передаёт роль или удаляет семью. Участник выходит из семьи;
    его общие операции остаются (автор обезличивается в purge_user)."""
    user = db.execute(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("Пользователь не найден")
    if not verify_password(user.password_hash, password):
        raise AccessDenied("Неверный пароль", code="INVALID_PASSWORD")

    membership = get_active_membership(db, user.id)
    if membership is not None:
        if membership.role == MemberRole.OWNER.value:
            raise BusinessConflict(
                "Передайте роль владельца другому участнику или удалите семью", code="OWNER_MUST_TRANSFER_OR_DELETE"
            )
        household = db.execute(
            select(Household).where(Household.id == membership.household_id).with_for_update()
            .execution_options(populate_existing=True)
        ).scalar_one()
        membership.status = MemberStatus.LEFT.value
        membership.ended_at = utcnow()
        membership.version = int(membership.version) + 1
        household.membership_version = int(household.membership_version) + 1
        add_outbox(
            db,
            event_type="MembershipChanged",
            aggregate_id=household.id,
            household_id=household.id,
            payload={"household_id": str(household.id), "membership_version": int(household.membership_version)},
        )

    user.status = UserStatus.DELETION_PENDING.value
    user.version = int(user.version) + 1
    revoke_all_sessions(db, user.id)
    add_audit(db, actor_id=user.id, household_id=None, action="user.deletion_requested", target_type="user", target_id=user.id)
    add_outbox(
        db,
        event_type="DeletionRequested",
        aggregate_id=user.id,
        household_id=None,
        payload={"target": "user", "target_id": str(user.id)},
    )
    db.flush()
    return user


def purge_user(db: Session, user_id: uuid.UUID) -> None:
    """Обезличивание аккаунта (исполняет worker в пределах 30 дней).

    Общие операции семьи сохраняются, author_user_id -> NULL («Удалённый участник»).
    Строка users остаётся обезличенной, чтобы не ломать историю членства; повтор безопасен."""
    user = db.get(User, user_id)
    if user is None:
        return
    db.execute(update(Transaction).where(Transaction.author_user_id == user_id).values(author_user_id=None))
    db.execute(update(GoalContribution).where(GoalContribution.author_user_id == user_id).values(author_user_id=None))
    db.execute(update(HistoryMonth).where(HistoryMonth.confirmed_by == user_id).values(confirmed_by=None))
    db.execute(update(Invitation).where(Invitation.created_by == user_id).values(created_by=None))
    db.execute(update(Invitation).where(Invitation.accepted_by == user_id).values(accepted_by=None))
    db.execute(update(AuditEvent).where(AuditEvent.actor_id == user_id).values(actor_id=None))
    for model in (Consent, UserToken, UserSession, Notification, AnomalyFeedback, RecommendationFeedback, SyncOperation):
        db.execute(delete(model).where(model.user_id == user_id))
    user.email_normalized = f"deleted+{user_id}@deleted.invalid"
    user.display_name = DELETED_USER_NAME
    user.password_hash = "!"
    user.verified_at = None
    user.notification_preferences = {}
    user.status = UserStatus.DELETION_PENDING.value
    db.flush()
