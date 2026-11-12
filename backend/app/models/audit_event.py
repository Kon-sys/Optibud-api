import uuid
from sqlalchemy import Column, String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base, JSONType

class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    actor_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True)
    action = Column(String(100), nullable=False)
    target_object = Column(String(100), nullable=False)
    details = Column(JSONType, nullable=True)
    occurred_at = Column(DateTime(timezone=True), server_default=func.now())
    result = Column(String(20), nullable=False, default="success")  # success, failure
