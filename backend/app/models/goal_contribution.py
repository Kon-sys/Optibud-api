import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean, Date
from sqlalchemy.dialects.postgresql import UUID
from app.models.base import Base

class GoalContribution(Base):
    __tablename__ = "goal_contributions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    goal_id = Column(UUID(as_uuid=True), ForeignKey("financial_goals.id"), nullable=False)
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    signed_amount_minor = Column(BigInteger, nullable=False)
    occurred_on = Column(Date, nullable=False)
    note = Column(String(255), nullable=True)
    version = Column(BigInteger, nullable=False, default=1)