import uuid

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class AnomalyFeedback(Base):
    """Отметка пользователя на аномалии (expected/useful/wrong) — одна на пользователя (upsert)."""

    __tablename__ = "anomaly_feedback"
    __table_args__ = (UniqueConstraint("anomaly_id", "user_id", name="uq_anomaly_feedback_user"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    anomaly_id = Column(UUID(as_uuid=True), ForeignKey("anomalies.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    label = Column(String(20), nullable=False)
