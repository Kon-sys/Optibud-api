import uuid

from sqlalchemy import BigInteger, CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, JSONType, in_list
from app.models.enums import ChangeAction


class ChangeLog(Base):


    __tablename__ = "change_log"
    __table_args__ = (
        UniqueConstraint("household_id", "seq", name="uq_change_log_household_seq"),
        CheckConstraint(in_list("action", ChangeAction), name="ck_change_log_action"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    seq = Column(BigInteger, nullable=False)
    entity_type = Column(String(50), nullable=False)
    entity_id = Column(UUID(as_uuid=True), nullable=False)
    action = Column(String(20), nullable=False)
    entity_version = Column(BigInteger, nullable=False)
    payload = Column(JSONType, nullable=True)  # полное представление либо tombstone
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
