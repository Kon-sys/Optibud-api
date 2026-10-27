import uuid

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.core.utils import utcnow
from app.models.base import Base, JSONType


class Notification(Base):


    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("user_id", "event_key", name="uq_notifications_user_event"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=True)
    event_key = Column(String(200), nullable=False)
    type = Column(String(50), nullable=False)
    payload = Column(JSONType, nullable=True)  # без сумм и описаний покупок
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
