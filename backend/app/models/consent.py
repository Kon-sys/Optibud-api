import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Consent(Base):
    __tablename__ = "consents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    purpose = Column(String(50), nullable=False)  # cross_household_analytics, assistant, product_telemetry
    text_version = Column(String(50), nullable=False)
    granted_at = Column(DateTime(timezone=True), server_default=func.now())
    revoked_at = Column(DateTime(timezone=True), nullable=True)