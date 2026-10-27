from sqlalchemy import BigInteger, CheckConstraint, Column, Date, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base, TimestampMixin, in_list
from app.models.enums import HistoryCompleteness


class HistoryMonth(TimestampMixin, Base):


    __tablename__ = "history_months"
    __table_args__ = (CheckConstraint(in_list("completeness", HistoryCompleteness), name="ck_history_completeness"),)

    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), primary_key=True)
    month = Column(Date, primary_key=True)
    completeness = Column(String(20), nullable=False, default=HistoryCompleteness.UNKNOWN.value)
    confirmed_by = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    confirmed_at = Column(DateTime(timezone=True), nullable=True)
    version = Column(BigInteger, nullable=False, default=1)
