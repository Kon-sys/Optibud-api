import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Anomaly(Base):
    __tablename__ = "anomalies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    transaction_id = Column(UUID(as_uuid=True), ForeignKey("transactions.id"), nullable=True)
    rule_code = Column(String(100), nullable=False)
    explanation = Column(String, nullable=False)
    actual_minor = Column(BigInteger, nullable=False)
    baseline_minor = Column(BigInteger, nullable=False)
    status = Column(String(20), nullable=False, default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())