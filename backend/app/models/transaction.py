import uuid
from sqlalchemy import Column, String, BigInteger, Date, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False, index=True)
    author_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    type = Column(String(20), nullable=False) # income, expense, refund, transfer
    amount_minor = Column(BigInteger, nullable=False) # Сумма в копейках
    currency = Column(String(3), nullable=False, default="BYN")
    operation_date = Column(Date, nullable=False, index=True)
    category_id = Column(UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True, index=True)
    merchant = Column(String(120), nullable=True)
    description = Column(String(500), nullable=True)
    source = Column(String(50), nullable=False, default="manual")
    external_id = Column(String(255), nullable=True)
    original_transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True)
    version = Column(BigInteger, nullable=False, default=1)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())