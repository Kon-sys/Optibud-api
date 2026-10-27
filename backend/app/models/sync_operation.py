import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, JSONType


class SyncOperation(Base):


    __tablename__ = "sync_operations"
    __table_args__ = (UniqueConstraint("user_id", "household_id", "operation_id", name="uq_sync_operations_key"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    operation_id = Column(UUID(as_uuid=True), nullable=False)
    request_hash = Column(String(64), nullable=False)
    result = Column(JSONType, nullable=False)
    processed_at = Column(DateTime(timezone=True), default=utcnow, nullable=False, index=True)


class ConsumedEntityId(Base):


    __tablename__ = "consumed_entity_ids"

    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), primary_key=True)
    entity_type = Column(String(50), primary_key=True)
    entity_id = Column(UUID(as_uuid=True), primary_key=True)
    deleted_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
