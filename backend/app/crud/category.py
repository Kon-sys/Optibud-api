"""Категории и правила категоризации (DR-08, DR-09, BR-01, BR-02, FR-16)."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.context import RequestContext
from app.core.errors import BusinessConflict, NotFound, ValidationFailed, field_error
from app.crud._common import (
    add_audit,
    authorize,
    ensure_version,
    record_change,
    require_version,
    unique_guard,
)
from app.models import Category, CategoryRule
from app.models.enums import CategorizationMethod, CategoryType, RuleMatchType
from app.schemas.category import (
    CategoryCreate,
    CategoryOut,
    CategoryPatch,
    CategoryRuleCreate,
    CategoryRulePatch,
    SystemCategoryCreate,
)

# Системный справочник (DR-08): (system_code, название, тип)
SYSTEM_CATEGORIES: list[tuple[str, str, str]] = [
    ("groceries", "Продукты", "expense"),
    ("housing", "Жильё и коммунальные услуги", "expense"),
    ("transport", "Транспорт", "expense"),
    ("health", "Здоровье", "expense"),
    ("education", "Образование", "expense"),
    ("children", "Дети", "expense"),
    ("clothing", "Одежда", "expense"),
    ("leisure", "Досуг", "expense"),
    ("subscriptions", "Связь и подписки", "expense"),
    ("other", "Прочее", "expense"),
    ("uncategorized", "Без категории", "expense"),
    ("salary", "Заработная плата", "income"),
    ("side_income", "Подработка", "income"),
    ("social", "Социальные выплаты", "income"),
    ("income_other", "Прочие доходы", "income"),
]
FALLBACK_CODE = {"expense": "uncategorized", "income": "income_other"}


def seed_system_categories(db: Session) -> int:
    """Идемпотентное наполнение справочника. Вызывать при старте/деплое. Возвращает число добавленных."""
    existing = set(db.execute(select(Category.system_code).where(Category.household_id.is_(None))).scalars().all())
    added = 0
    for code, name, type_ in SYSTEM_CATEGORIES:
        if code in existing:
            continue
        db.add(Category(id=uuid.uuid4(), household_id=None, parent_id=None, system_code=code, name=name, type=type_, version=1))
        added += 1
    db.flush()
    return added


def _payload(category: Category) -> dict[str, Any]:
    return CategoryOut.model_validate(category).model_dump(mode="json")


def get_system_category(db: Session, system_code: str) -> Category | None:
    return db.execute(
        select(Category).where(Category.system_code == system_code, Category.household_id.is_(None))
    ).scalar_one_or_none()


def get_accessible_category(
    db: Session, household_id: uuid.UUID, category_id: uuid.UUID, *, field: str = "category_id"
) -> Category:
    """Категория должна быть системной либо своей семьи; чужая — как несуществующая."""
    category = db.get(Category, category_id)
    if category is None or (category.household_id is not None and category.household_id != household_id):
        raise ValidationFailed("Категория не найдена", field_errors=[field_error(field, "Категория не найдена")])
    return category


# --------------------------------------------------------------------------- #
# Семейные категории
# --------------------------------------------------------------------------- #
def list_categories(db: Session, ctx: RequestContext, include_archived: bool = False) -> list[Category]:
    household, _ = authorize(db, ctx)
    stmt = select(Category).where(or_(Category.household_id.is_(None), Category.household_id == household.id))
    if not include_archived:
        stmt = stmt.where(Category.is_archived.is_(False))
    return list(db.execute(stmt.order_by(Category.type, Category.name)).scalars().all())


def create_category(db: Session, ctx: RequestContext, data: CategoryCreate) -> Category:
    """POST /categories — подкатегория семьи с системным родителем того же типа (владелец)."""
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    parent = db.get(Category, data.parent_id)
    if parent is None or parent.household_id is not None:
        raise ValidationFailed(field_errors=[field_error("parent_id", "Родитель должен быть системной категорией")])
    if parent.type != data.type:
        raise ValidationFailed(field_errors=[field_error("type", "Тип должен совпадать с типом родителя")])

    category = Category(
        id=uuid.uuid4(),
        household_id=household.id,
        parent_id=parent.id,
        system_code=None,
        name=data.name,
        type=data.type,
        is_archived=False,
        version=1,
    )
    with unique_guard(db, "CATEGORY_NAME_TAKEN", "Категория с таким названием уже существует"):
        db.add(category)
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="category", entity_id=category.id,
        action="create", entity_version=1, payload=_payload(category), event_type="CategoryChanged",
    )
    return category


def update_category(
    db: Session, ctx: RequestContext, category_id: uuid.UUID, patch: CategoryPatch, expected_version: int | None
) -> Category:
    """PATCH /categories/{id}: переименование и архивация. Физически категории не удаляются (DR-09)."""
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    category = db.execute(
        select(Category).where(Category.id == category_id, Category.household_id == household.id).with_for_update()
    ).scalar_one_or_none()
    if category is None:
        raise NotFound("Категория не найдена")
    ensure_version(int(category.version), expected, _payload(category))

    data = patch.model_dump(exclude_unset=True)
    with unique_guard(db, "CATEGORY_NAME_TAKEN", "Категория с таким названием уже существует"):
        if data.get("name") is not None:
            category.name = data["name"]
        if data.get("is_archived") is not None:
            category.is_archived = data["is_archived"]
        category.version = int(category.version) + 1
    record_change(
        db, household, actor_id=ctx.user_id, entity_type="category", entity_id=category.id,
        action="update", entity_version=int(category.version), payload=_payload(category), event_type="CategoryChanged",
    )
    return category


# --------------------------------------------------------------------------- #
# Администратор: системные категории (отдельная схема полномочий, /admin/v1)
# --------------------------------------------------------------------------- #
def admin_create_system_category(db: Session, admin_id: uuid.UUID, data: SystemCategoryCreate) -> Category:
    category = Category(
        id=uuid.uuid4(), household_id=None, parent_id=None, system_code=data.system_code,
        name=data.name, type=data.type, version=1,
    )
    with unique_guard(db, "CATEGORY_EXISTS", "Системная категория уже существует"):
        db.add(category)
    add_audit(db, actor_id=admin_id, household_id=None, action="system_category.created", target_type="category", target_id=category.id)
    return category


def admin_update_system_category(
    db: Session, admin_id: uuid.UUID, category_id: uuid.UUID, patch: CategoryPatch, expected_version: int | None
) -> Category:
    expected = require_version(expected_version)
    category = db.execute(
        select(Category).where(Category.id == category_id, Category.household_id.is_(None)).with_for_update()
    ).scalar_one_or_none()
    if category is None:
        raise NotFound("Категория не найдена")
    ensure_version(int(category.version), expected)
    data = patch.model_dump(exclude_unset=True)
    with unique_guard(db, "CATEGORY_EXISTS", "Системная категория с таким названием уже существует"):
        if data.get("name") is not None:
            category.name = data["name"]
        if data.get("is_archived") is not None:
            category.is_archived = data["is_archived"]
        category.version = int(category.version) + 1
    add_audit(db, actor_id=admin_id, household_id=None, action="system_category.updated", target_type="category", target_id=category.id)
    return category


# --------------------------------------------------------------------------- #
# Правила категоризации семьи
# --------------------------------------------------------------------------- #
def _rule_payload(rule: CategoryRule) -> dict[str, Any]:
    from app.schemas.category import CategoryRuleOut
    return CategoryRuleOut.model_validate(rule).model_dump(mode="json")


def list_rules(db: Session, ctx: RequestContext) -> list[CategoryRule]:
    household, _ = authorize(db, ctx)
    return list(
        db.execute(
            select(CategoryRule).where(CategoryRule.household_id == household.id)
            .order_by(CategoryRule.priority.desc(), CategoryRule.created_at)
        ).scalars().all()
    )


def create_rule(db: Session, ctx: RequestContext, data: CategoryRuleCreate) -> CategoryRule:
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    category = get_accessible_category(db, household.id, data.category_id)
    if category.is_archived:
        raise ValidationFailed(field_errors=[field_error("category_id", "Категория архивирована")])
    rule = CategoryRule(
        id=uuid.uuid4(), household_id=household.id, match_type=data.match_type,
        pattern=data.pattern, category_id=category.id, priority=data.priority, version=1,
    )
    db.add(rule)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="category_rule.created", target_type="category_rule", target_id=rule.id)
    db.flush()
    return rule


def update_rule(
    db: Session, ctx: RequestContext, rule_id: uuid.UUID, patch: CategoryRulePatch, expected_version: int | None
) -> CategoryRule:
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    rule = db.execute(
        select(CategoryRule).where(CategoryRule.id == rule_id, CategoryRule.household_id == household.id).with_for_update()
    ).scalar_one_or_none()
    if rule is None:
        raise NotFound("Правило не найдено")
    ensure_version(int(rule.version), expected, _rule_payload(rule))
    data = patch.model_dump(exclude_unset=True)
    if data.get("category_id") is not None:
        category = get_accessible_category(db, household.id, data["category_id"])
        if category.is_archived:
            raise ValidationFailed(field_errors=[field_error("category_id", "Категория архивирована")])
    for key in ("match_type", "pattern", "category_id", "priority"):
        if data.get(key) is not None:
            setattr(rule, key, data[key])
    rule.version = int(rule.version) + 1
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="category_rule.updated", target_type="category_rule", target_id=rule.id)
    db.flush()
    return rule


def delete_rule(db: Session, ctx: RequestContext, rule_id: uuid.UUID, expected_version: int | None) -> None:
    expected = require_version(expected_version)
    household, _ = authorize(db, ctx, lock=True, require_owner=True)
    rule = db.execute(
        select(CategoryRule).where(CategoryRule.id == rule_id, CategoryRule.household_id == household.id).with_for_update()
    ).scalar_one_or_none()
    if rule is None:
        raise NotFound("Правило не найдено")
    ensure_version(int(rule.version), expected, _rule_payload(rule))
    db.delete(rule)
    add_audit(db, actor_id=ctx.user_id, household_id=household.id, action="category_rule.deleted", target_type="category_rule", target_id=rule_id)
    db.flush()


# --------------------------------------------------------------------------- #
# Автокатегоризация (FR-16): правило семьи -> системное правило -> «Без категории».
# Ручной выбор имеет наивысший приоритет и сюда не попадает. Модель классификации
# (TF-IDF) подключается отдельным шагом в аналитическом сервисе.
# --------------------------------------------------------------------------- #
def _norm(value: str | None) -> str:
    return " ".join((value or "").lower().split())


def _rule_matches(rule: CategoryRule, merchant: str, haystack: str) -> bool:
    pattern = _norm(rule.pattern)
    if not pattern:
        return False
    if rule.match_type == RuleMatchType.EQUALS.value:
        return merchant == pattern
    if rule.match_type == RuleMatchType.STARTS_WITH.value:
        return merchant.startswith(pattern)
    return pattern in haystack  # contains


def auto_categorize(
    db: Session, household_id: uuid.UUID, tx_type: str, merchant: str | None, description: str | None
) -> tuple[uuid.UUID | None, str]:
    """Возвращает (category_id, categorization_method). (None, 'none') — подходящей категории нет."""
    merchant_n = _norm(merchant)
    haystack = f"{merchant_n} {_norm(description)}".strip()
    if not haystack:
        return None, CategorizationMethod.NONE.value

    for scope_filter, method in (
        (CategoryRule.household_id == household_id, CategorizationMethod.FAMILY_RULE.value),
        (CategoryRule.household_id.is_(None), CategorizationMethod.SYSTEM_RULE.value),
    ):
        rules = db.execute(
            select(CategoryRule).where(scope_filter).order_by(CategoryRule.priority.desc(), CategoryRule.created_at)
        ).scalars().all()
        for rule in rules:
            if not _rule_matches(rule, merchant_n, haystack):
                continue
            category = db.get(Category, rule.category_id)
            if category is None or category.is_archived or category.type != tx_type:
                continue
            if category.household_id not in (None, household_id):
                continue
            return category.id, method
    return None, CategorizationMethod.NONE.value


def fallback_category(db: Session, tx_type: str) -> Category:
    """«Без категории» для расхода, «Прочие доходы» для дохода."""
    category = get_system_category(db, FALLBACK_CODE[tx_type])
    if category is None:
        raise BusinessConflict(
            "Системный справочник категорий не загружен (seed_system_categories)", code="SYSTEM_CATEGORIES_MISSING"
        )
    return category
