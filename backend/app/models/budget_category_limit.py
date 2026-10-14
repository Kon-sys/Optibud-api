import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class BudgetCategoryLimit(Base):
    __tablename__ = "budget_category_limits"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    budget_id = Column(UUID(as_uuid=True), ForeignKey("budgets.id"), nullable=False)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=False)
    limit_minor = Column(BigInteger, nullable=False)