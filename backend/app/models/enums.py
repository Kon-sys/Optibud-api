
from enum import StrEnum


class UserStatus(StrEnum):
    PENDING = "pending"
    ACTIVE = "active"
    BLOCKED = "blocked"
    DELETION_PENDING = "deletion_pending"


class HouseholdStatus(StrEnum):
    ACTIVE = "active"
    DELETION_PENDING = "deletion_pending"


class MemberRole(StrEnum):
    OWNER = "owner"
    MEMBER = "member"


class MemberStatus(StrEnum):
    ACTIVE = "active"
    LEFT = "left"
    REMOVED = "removed"


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    CANCELLED = "cancelled"
    REVOKED = "revoked"   # заменено повторной отправкой
    EXPIRED = "expired"


class TransactionType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"
    REFUND = "refund"
    TRANSFER = "transfer"


class CategoryType(StrEnum):
    INCOME = "income"
    EXPENSE = "expense"


class CategorizationMethod(StrEnum):
    MANUAL = "manual"
    FAMILY_RULE = "family_rule"
    SYSTEM_RULE = "system_rule"
    MODEL = "model"
    NONE = "none"


class RuleMatchType(StrEnum):
    EQUALS = "equals"
    CONTAINS = "contains"
    STARTS_WITH = "starts_with"


class GoalStatus(StrEnum):
    ACTIVE = "active"
    ACHIEVED = "achieved"
    OVERDUE = "overdue"
    ARCHIVED = "archived"


class ResultStatus(StrEnum):
    ACTIVE = "active"
    STALE = "stale"
    RESOLVED = "resolved"   # аномалии
    EXPIRED = "expired"     # рекомендации


class ForecastStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    EXPERIMENTAL = "experimental"


class AnomalyLabel(StrEnum):
    EXPECTED = "expected"
    USEFUL = "useful"
    WRONG = "wrong"


class RecommendationAction(StrEnum):
    USEFUL = "useful"
    HIDDEN = "hidden"


class ConsentPurpose(StrEnum):
    CROSS_HOUSEHOLD_ANALYTICS = "cross_household_analytics"
    ASSISTANT = "assistant"
    PRODUCT_TELEMETRY = "product_telemetry"


class TokenPurpose(StrEnum):
    VERIFY_EMAIL = "verify_email"
    PASSWORD_RESET = "password_reset"
    EMAIL_CHANGE = "email_change"


class ChangeAction(StrEnum):
    CREATE = "create"
    UPDATE = "update"
    DELETE = "delete"


class OutboxStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"


class HistoryCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
