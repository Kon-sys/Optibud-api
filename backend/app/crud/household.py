"""Семья, члены, приглашения, передача владения (FR-06, FR-09, FR-10, BR-03, BR-04)."""
from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import AccessDenied, BusinessConflict, NotFound, ValidationFailed, field_error
from app.core.security import new_token, token_hash, verify_password
from app.core.utils import as_utc, first_day_of_month, normalize_email, today_in, utcnow
from app.crud._common import (
    add_audit,
    add_outbox,
    authorize,
    ensure_version,
    get_active_membership,
    require_version,
    unique_guard,
)
from app.models import (
    Budget,
    Household,
    HouseholdMember,
    HouseholdProfileSnapshot,
    Invitation,
    User,
)
from app.models.enums import (
    HouseholdStatus,
    InvitationStatus,
    MemberRole,
    MemberStatus,
    UserStatus,
)
from app.schemas.household import HouseholdCreate, HouseholdPatch

MAX_MEMBERS = 10
INVITATION_TTL = timedelta(hours=72)


def _membership_changed(db: Session, household: Household) -> None:
    household.membership_version = int(household.membership_version) + 1
    add_outbox(
        db,
        event_type="MembershipChanged",
        aggregate_id=household.id,
        household_id=household.id,
        payload={"household_id": str(household.id), "membership_version": int(household.membership_version)},
    )


def _active_member_count(db: Session, household_id: uuid.UUID) -> int:
    return int(
        db.execute(
            select(func.count()).select_from(HouseholdMember).where(
                HouseholdMember.household_id == household_id, HouseholdMember.status == MemberStatus.ACTIVE.value
            )
        ).scalar_one()
    )


# --------------------------------------------------------------------------- #
# Семья
# --------------------------------------------------------------------------- #
def create_household(db: Session, user_id: uuid.UUID, data: HouseholdCreate) -> tuple[Household, HouseholdMember]:
    """POST /households. Создатель — владелец; BYN и Europe/Minsk; создаётся бюджет текущего месяца."""
    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        raise AccessDenied("Для создания семьи подтвердите адрес электронной почты")
    if get_active_membership(db, user_id) is not None:
        raise BusinessConflict("Вы уже состоите в семье", code="ALREADY_IN_HOUSEHOLD")

    now = utcnow()
    household = Household(
        id=uuid.uuid4(),
        name=data.name,
        adults_count=data.adults_count,
        children_count=data.children_count,
        region_code=data.region_code,
        income_band=data.income_band,
        currency="BYN",
        timezone="Europe/Minsk",
        status=HouseholdStatus.ACTIVE.value,
        version=1,
        data_version=1,
        change_seq=0,
        membership_version=1,
    )
    member = HouseholdMember(
        id=uuid.uuid4(),
        household_id=household.id,
        user_id=user_id,
        role=MemberRole.OWNER.value,
        status=MemberStatus.ACTIVE.value,
        joined_at=now,
        version=1,
    )
    # Все объекты добавляются внутри guard: частичный UNIQUE «одна активная семья»
    # защищает от гонки двух параллельных создателей.
    with unique_guard(db, "ALREADY_IN_HOUSEHOLD", "Вы уже состоите в семье"):
        db.add(household)
        db.flush()  # households раньше зависимых строк (FK)
        db.add(member)
        db.add(
            HouseholdProfileSnapshot(
                id=uuid.uuid4(),
                household_id=household.id,
                adults_count=data.adults_count,
                children_count=data.children_count,
                region_code=data.region_code,
                income_band=data.income_band,
                valid_from=now,
            )
        )
        db.add(
            Budget(
                id=uuid.uuid4(),
                household_id=household.id,
                month=first_day_of_month(today_in(household.timezone)),
                currency="BYN",
                version=1,
            )
        )
    add_audit(db, actor_id=user_id, household_id=household.id, action="household.created", target_type="household", target_id=household.id)
    _membership_changed(db, household)
    return household, member


def get_current_household(db: Session, user_id: uuid.UUID) -> tuple[Household, HouseholdMember] | None:
    """GET /households/current — семья или None."""
    member = get_active_membership(db, user_id)
    if member is None:
        return None
    household = db.get(Household, member.household_id)
    if household is None or household.status != HouseholdStatus.ACTIVE.value:
        return None
    return household, member


def get_household(db: Session, ctx: RequestContext) -> Household:
    household, _ = authorize(db, ctx)
    return household


def update_household(db: Session, ctx: RequestContext, data: HouseholdPatch, expected_version: int | None) -> Household:
    """PATCH /households/{h} (If-Match, только владелец). Изменение состава версионируется снимком (DR-04)."""
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    ensure_version(int(household.version), expected)

    changes = data.model_dump(exclude_unset=True)
    profile_fields = {"adults_count", "children_count", "region_code", "income_band"}
    profile_changed = any(k in changes and changes[k] != getattr(household, k) for k in profile_fields)

    for key, value in changes.items():
        if value is None and key in ("name", "adults_count", "children_count"):
            raise ValidationFailed(field_errors=[field_error(key, "Поле обязательно")])
        setattr(household, key, value)

    if profile_changed:
        now = utcnow()
        db.execute(
            update(HouseholdProfileSnapshot)
            .where(
                HouseholdProfileSnapshot.household_id == household.id,
                HouseholdProfileSnapshot.valid_to.is_(None),
            )
            .values(valid_to=now)
        )
        db.add(
            HouseholdProfileSnapshot(
                id=uuid.uuid4(),
                household_id=household.id,
                adults_count=household.adults_count,
                children_count=household.children_count,
                region_code=household.region_code,
                income_band=household.income_band,
                valid_from=now,
            )
        )
    household.version = int(household.version) + 1
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="household.updated", target_type="household", target_id=household.id)
    db.flush()
    return household


# --------------------------------------------------------------------------- #
# Участники
# --------------------------------------------------------------------------- #
def list_members(db: Session, ctx: RequestContext) -> list[tuple[HouseholdMember, str]]:
    """GET /households/{h}/members: (членство, display_name). Email других участников не возвращается."""
    household, _ = authorize(db, ctx)
    rows = db.execute(
        select(HouseholdMember, User.display_name)
        .join(User, User.id == HouseholdMember.user_id)
        .where(HouseholdMember.household_id == household.id, HouseholdMember.status == MemberStatus.ACTIVE.value)
        .order_by(HouseholdMember.joined_at, HouseholdMember.id)
    ).all()
    return [(m, name) for m, name in rows]


def remove_member(db: Session, ctx: RequestContext, member_id: uuid.UUID) -> None:
    """DELETE /households/{h}/members/{id} — исключение (только владелец). Общие операции остаются."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    target = db.execute(
        select(HouseholdMember).where(
            HouseholdMember.id == member_id,
            HouseholdMember.household_id == household.id,
            HouseholdMember.status == MemberStatus.ACTIVE.value,
        ).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("Участник не найден")
    if target.role == MemberRole.OWNER.value:
        raise BusinessConflict("Владельца нельзя исключить; сначала передайте роль", code="CANNOT_REMOVE_OWNER")
    target.status = MemberStatus.REMOVED.value
    target.ended_at = utcnow()
    target.version = int(target.version) + 1
    _membership_changed(db, household)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="member.removed", target_type="member", target_id=target.id)
    db.flush()


def leave_household(db: Session, ctx: RequestContext) -> None:
    """POST /households/{h}/leave. Владелец не может выйти, не оставив бесхозную семью (BR-03)."""
    household, member = authorize(db, ctx, lock=True)
    if member.role == MemberRole.OWNER.value:
        raise BusinessConflict(
            "Владелец сначала передаёт роль другому участнику либо удаляет семью", code="OWNER_CANNOT_LEAVE"
        )
    member.status = MemberStatus.LEFT.value
    member.ended_at = utcnow()
    member.version = int(member.version) + 1
    _membership_changed(db, household)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="member.left", target_type="member", target_id=member.id)
    db.flush()


def transfer_owner(db: Session, ctx: RequestContext, target_member_id: uuid.UUID, password: str) -> Household:
    """POST /households/{h}/transfer-owner. Атомарная смена ролей с подтверждением пароля (FR-10)."""
    household, owner = authorize(db, ctx, lock=True, require_owner=True)
    user = db.get(User, ctx.user_id)
    if user is None or not verify_password(user.password_hash, password):
        raise AccessDenied("Неверный пароль", code="INVALID_PASSWORD")
    target = db.execute(
        select(HouseholdMember).where(
            HouseholdMember.id == target_member_id,
            HouseholdMember.household_id == household.id,
            HouseholdMember.status == MemberStatus.ACTIVE.value,
        ).with_for_update()
    ).scalar_one_or_none()
    if target is None:
        raise NotFound("Участник не найден")
    if target.id == owner.id:
        raise BusinessConflict("Вы уже владелец семьи", code="ALREADY_OWNER")

    # Порядок важен из-за частичного UNIQUE «один активный владелец»: сначала снимаем роль.
    owner.role = MemberRole.MEMBER.value
    owner.version = int(owner.version) + 1
    db.flush()
    target.role = MemberRole.OWNER.value
    target.version = int(target.version) + 1
    db.flush()
    _membership_changed(db, household)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="household.owner_transferred", target_type="member", target_id=target.id)
    db.flush()
    return household


def delete_household(db: Session, ctx: RequestContext, password: str, expected_version: int | None) -> None:
    """DELETE /households/{h}. Доступ закрывается немедленно (в этой же транзакции);
    физическое удаление данных выполняет worker по событию DeletionRequested (DR-12)."""
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    ensure_version(int(household.version), expected)
    user = db.get(User, ctx.user_id)
    if user is None or not verify_password(user.password_hash, password):
        raise AccessDenied("Неверный пароль", code="INVALID_PASSWORD")

    now = utcnow()
    household.status = HouseholdStatus.DELETION_PENDING.value
    household.version = int(household.version) + 1
    db.execute(
        update(HouseholdMember)
        .where(HouseholdMember.household_id == household.id, HouseholdMember.status == MemberStatus.ACTIVE.value)
        .values(status=MemberStatus.REMOVED.value, ended_at=now)
    )
    db.execute(
        update(Invitation)
        .where(Invitation.household_id == household.id, Invitation.status == InvitationStatus.PENDING.value)
        .values(status=InvitationStatus.CANCELLED.value)
    )
    _membership_changed(db, household)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="household.deletion_requested", target_type="household", target_id=household.id)
    add_outbox(
        db,
        event_type="DeletionRequested",
        aggregate_id=household.id,
        household_id=household.id,
        payload={"target": "household", "target_id": str(household.id)},
    )
    db.flush()


# --------------------------------------------------------------------------- #
# Приглашения
# --------------------------------------------------------------------------- #
def create_invitation(db: Session, ctx: RequestContext, email: str) -> tuple[Invitation, str]:
    """POST /households/{h}/invitations. Возвращает (приглашение, raw_token для письма).
    Повторная отправка отзывает предыдущее приглашение для этой пары (FR-09)."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    email_n = normalize_email(email)

    if _active_member_count(db, household.id) >= MAX_MEMBERS:
        raise BusinessConflict("В семье уже 10 участников", code="MEMBER_LIMIT_REACHED")
    already = db.execute(
        select(HouseholdMember.id)
        .join(User, User.id == HouseholdMember.user_id)
        .where(
            HouseholdMember.household_id == household.id,
            HouseholdMember.status == MemberStatus.ACTIVE.value,
            User.email_normalized == email_n,
        )
    ).first()
    if already is not None:
        raise BusinessConflict("Этот пользователь уже состоит в семье", code="ALREADY_MEMBER")

    db.execute(
        update(Invitation)
        .where(
            Invitation.household_id == household.id,
            Invitation.email_normalized == email_n,
            Invitation.status == InvitationStatus.PENDING.value,
        )
        .values(status=InvitationStatus.REVOKED.value)
    )
    db.flush()  # освобождаем частичный UNIQUE до вставки нового приглашения

    raw = new_token()
    invitation = Invitation(
        id=uuid.uuid4(),
        household_id=household.id,
        email_normalized=email_n,
        token_hash=token_hash(raw),
        expires_at=utcnow() + INVITATION_TTL,
        status=InvitationStatus.PENDING.value,
        created_by=ctx.user_id,
        version=1,
    )
    with unique_guard(db, "INVITATION_EXISTS", "Приглашение уже существует"):
        db.add(invitation)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="invitation.created", target_type="invitation", target_id=invitation.id)
    return invitation, raw


def list_invitations(db: Session, ctx: RequestContext) -> list[Invitation]:
    """GET /households/{h}/invitations — ожидающие приглашения владельца (просроченные не показываются)."""
    household, _ = authorize(db, ctx, require_owner=True)
    now = utcnow()
    rows = db.execute(
        select(Invitation)
        .where(Invitation.household_id == household.id, Invitation.status == InvitationStatus.PENDING.value)
        .order_by(Invitation.created_at.desc())
    ).scalars().all()
    return [i for i in rows if as_utc(i.expires_at) > now]


def cancel_invitation(db: Session, ctx: RequestContext, invitation_id: uuid.UUID) -> None:
    """DELETE /households/{h}/invitations/{id}."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    invitation = db.execute(
        select(Invitation).where(Invitation.id == invitation_id, Invitation.household_id == household.id).with_for_update()
    ).scalar_one_or_none()
    if invitation is None:
        raise NotFound("Приглашение не найдено")
    if invitation.status != InvitationStatus.PENDING.value:
        raise BusinessConflict("Приглашение уже не действует", code="INVITATION_NOT_PENDING")
    invitation.status = InvitationStatus.CANCELLED.value
    invitation.version = int(invitation.version) + 1
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="invitation.cancelled", target_type="invitation", target_id=invitation.id)
    db.flush()


def accept_invitation(db: Session, user_id: uuid.UUID, raw_token: str) -> tuple[HouseholdMember, Household]:
    """POST /invitations/accept (п. 6.2). Атомарно: проверка лимита, адреса, членства и создание участника.

    Порядок блокировок: строка семьи -> строка приглашения (как у остальных команд)."""
    probe = db.execute(select(Invitation).where(Invitation.token_hash == token_hash(raw_token))).scalar_one_or_none()
    if probe is None:
        raise ValidationFailed("Приглашение недействительно", code="INVALID_INVITATION")

    household = db.execute(
        select(Household).where(Household.id == probe.household_id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    invitation = db.execute(
        select(Invitation).where(Invitation.id == probe.id).with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    if household is None or household.status != HouseholdStatus.ACTIVE.value:
        raise ValidationFailed("Приглашение недействительно", code="INVALID_INVITATION")

    if invitation.status != InvitationStatus.PENDING.value:
        raise ValidationFailed("Приглашение уже использовано или отменено", code="INVALID_INVITATION")
    if as_utc(invitation.expires_at) <= utcnow():
        invitation.status = InvitationStatus.EXPIRED.value
        db.flush()
        raise ValidationFailed("Срок приглашения истёк", code="INVITATION_EXPIRED")

    user = db.get(User, user_id)
    if user is None or user.status != UserStatus.ACTIVE.value or user.verified_at is None:
        raise AccessDenied("Адрес электронной почты не подтверждён")
    if user.email_normalized != invitation.email_normalized:
        raise AccessDenied("Приглашение выпущено на другой адрес", code="INVITATION_EMAIL_MISMATCH")
    if get_active_membership(db, user_id) is not None:
        raise BusinessConflict("Вы уже состоите в семье", code="ALREADY_IN_HOUSEHOLD")
    if _active_member_count(db, household.id) >= MAX_MEMBERS:
        raise BusinessConflict("В семье уже 10 участников", code="MEMBER_LIMIT_REACHED")

    member = HouseholdMember(
        id=uuid.uuid4(),
        household_id=household.id,
        user_id=user_id,
        role=MemberRole.MEMBER.value,
        status=MemberStatus.ACTIVE.value,
        joined_at=utcnow(),
        version=1,
    )
    with unique_guard(db, "ALREADY_IN_HOUSEHOLD", "Вы уже состоите в семье"):
        db.add(member)
    invitation.status = InvitationStatus.ACCEPTED.value
    invitation.accepted_by = user_id
    invitation.version = int(invitation.version) + 1
    # Присоединение нового участника автоматически приостанавливает общую аналитику
    # до его согласия — это следует из расчёта effective_consent (app.crud.consent).
    _membership_changed(db, household)
    add_audit(db, actor_id=user_id, household_id=household.id, action="invitation.accepted", target_type="invitation", target_id=invitation.id)
    db.flush()
    return member, household
