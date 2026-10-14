import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    rule_code = Column(String(100), nullable=False)
    text = Column(String, nullable=False)
    priority = Column(Integer, nullable=False, default=0)
    status = Column(String(20), nullable=False, default="active")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    data_version = Column(BigInteger, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())