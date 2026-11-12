import uuid

from sqlalchemy import Column, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID

from app.models.base import Base


class RecommendationFeedback(Base):
    """Отметка пользователя на рекомендации (useful/hidden). Пользователь может иметь обе отметки сразу."""

    __tablename__ = "recommendation_feedback"
    __table_args__ = (
        UniqueConstraint("recommendation_id", "user_id", "action", name="uq_recommendation_feedback_user_action"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    recommendation_id = Column(
        UUID(as_uuid=True), ForeignKey("recommendations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    action = Column(String(20), nullable=False)
