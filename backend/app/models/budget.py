import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.models.base import Base

class Budget(Base):
    __tablename__ = "budgets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    month = Column(Date, nullable=False)  # Первый день месяца
    total_limit_minor = Column(BigInteger, nullable=True)
    planned_income_minor = Column(BigInteger, nullable=True)
    currency = Column(String(3), nullable=False, default="BYN")
    version = Column(BigInteger, nullable=False, default=1)

    limits = relationship(
        "BudgetCategoryLimit", backref="budget", cascade="all, delete-orphan", lazy="selectin"
    )
