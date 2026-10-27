import uuid

from sqlalchemy import BigInteger, CheckConstraint, Column, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, in_list
from app.models.enums import RuleMatchType


class CategoryRule(TimestampMixin, Base):


    __tablename__ = "category_rules"
    __table_args__ = (CheckConstraint(in_list("match_type", RuleMatchType), name="ck_category_rules_match_type"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True, index=True)
    match_type = Column(String(20), nullable=False)
    pattern = Column(String(120), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    version = Column(BigInteger, nullable=False, default=1)
