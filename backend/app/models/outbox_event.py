import uuid

from sqlalchemy import CheckConstraint, Column, DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, JSONType, in_list
from app.models.enums import OutboxStatus


class OutboxEvent(Base):


    __tablename__ = "outbox_events"
    __table_args__ = (CheckConstraint(in_list("status", OutboxStatus), name="ck_outbox_status"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)  # event_id
    event_type = Column(String(100), nullable=False)
    event_version = Column(Integer, nullable=False, default=1)
    aggregate_id = Column(UUID(as_uuid=True), nullable=False)
    household_id = Column(UUID(as_uuid=True), nullable=True)
    correlation_id = Column(UUID(as_uuid=True), nullable=True)
    payload = Column(JSONType, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default=OutboxStatus.PENDING.value)
    occurred_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    delivered_at = Column(DateTime(timezone=True), nullable=True)


Index("ix_outbox_pending", OutboxEvent.status, OutboxEvent.occurred_at)
