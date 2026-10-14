import uuid
from sqlalchemy import Column, String, BigInteger, ForeignKey, Boolean, Date, DateTime
from sqlalchemy.dialects.postgresql import UUID
from app.core.database import Base

class Forecast(Base):
    __tablename__ = "forecasts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    household_id = Column(UUID(as_uuid=True), ForeignKey("households.id"), nullable=False)
    target_month = Column(Date, nullable=False)
    predicted_minor = Column(BigInteger, nullable=False)
    lower_minor = Column(BigInteger, nullable=True)
    upper_minor = Column(BigInteger, nullable=True)
    model_version = Column(String(50), nullable=False)
    data_version = Column(BigInteger, nullable=False)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())