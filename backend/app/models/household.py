import uuid
from sqlalchemy import Column, String, Integer, BigInteger, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from app.core.database import Base

class Household(Base):
    __tablename__ = "households"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(80), nullable=False)
    adults_count = Column(Integer, nullable=False, default=1)
    children_count = Column(Integer, nullable=False, default=0)
    region_code = Column(String(50), nullable=True)
    income_band = Column(String(50), nullable=True)
    currency = Column(String(3), nullable=False, default="BYN")
    timezone = Column(String(50), nullable=False, default="Europe/Minsk")
    status = Column(String(20), nullable=False, default="active")
    data_version = Column(BigInteger, nullable=False, default=1)
    change_seq = Column(BigInteger, nullable=False, default=0)
    membership_version = Column(BigInteger, nullable=False, default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())