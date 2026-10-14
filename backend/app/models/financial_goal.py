import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class FinancialGoal(Base):
    __tablename__ = "financial_goals"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    title = Column(String(120), nullable=False)
    target_minor = Column(BigInteger, nullable=False)
    target_date = Column(Date, nullable=False)
    status = Column(String(20), nullable=False, default="active")  # active, achieved, overdue, archived
    version = Column(BigInteger, nullable=False, default=1)